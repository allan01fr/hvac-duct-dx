"""Leitor das planilhas QDMT (Ceiling Concealed Ducted Split Systems.xlsx).

Leitura e validações movidas de `build_db.py`; aqui nada é gravado em banco.
"""
from __future__ import annotations

import logging
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

import pandas as pd

from ductdx.catalogo.fontes import TabelasFamilia

LOGGER = logging.getLogger("build_db")


class BuildError(RuntimeError):
    """Raised when the database cannot be built or validated safely."""


def require_file(path: Path, description: str) -> None:
    """Raise a clear error when a required file is missing."""
    if not path.is_file():
        raise BuildError(f"{description} was not found: {path}")


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize column names without changing the source values."""
    result = df.copy()
    result.columns = [str(column).strip() for column in result.columns]
    return result


def read_sheet(
    workbook: Path,
    sheet_name: str,
    required_columns: Sequence[str],
) -> pd.DataFrame:
    """Read and validate one Excel worksheet."""
    require_file(workbook, f"Workbook for sheet {sheet_name!r}")

    try:
        dataframe = pd.read_excel(workbook, sheet_name=sheet_name)
    except ValueError as exc:
        raise BuildError(
            f"Could not read worksheet {sheet_name!r} from {workbook.name}: {exc}"
        ) from exc
    except (OSError, ImportError, TypeError, KeyError, zipfile.BadZipFile) as exc:
        raise BuildError(
            f"Failed to read worksheet {sheet_name!r} from {workbook}: {exc}"
        ) from exc

    dataframe = normalize_columns(dataframe)
    missing = sorted(set(required_columns) - set(dataframe.columns))
    if missing:
        raise BuildError(
            f"Worksheet {sheet_name!r} in {workbook.name} is missing columns: "
            f"{', '.join(missing)}"
        )

    # Remove fully empty rows. Other missing values are preserved and validated
    # by the table-specific checks below.
    dataframe = dataframe.dropna(how="all").reset_index(drop=True)
    if dataframe.empty:
        raise BuildError(
            f"Worksheet {sheet_name!r} in {workbook.name} contains no data rows"
        )

    LOGGER.debug(
        "Read %s / %s: %d rows x %d columns",
        workbook.name,
        sheet_name,
        len(dataframe),
        len(dataframe.columns),
    )
    return dataframe


def assert_unique_values(
    dataframe: pd.DataFrame,
    column: str,
    context: str,
) -> None:
    """Require a column to contain non-null unique values."""
    if dataframe[column].isna().any():
        raise BuildError(f"{context}: column {column!r} contains NULL values")
    if dataframe[column].duplicated().any():
        duplicates = sorted(dataframe.loc[dataframe[column].duplicated(), column].unique())
        raise BuildError(
            f"{context}: column {column!r} contains duplicate values: {duplicates}"
        )


def assert_no_nulls(
    dataframe: pd.DataFrame,
    columns: Iterable[str],
    context: str,
) -> None:
    """Require selected columns to contain no NULL values."""
    for column in columns:
        if dataframe[column].isna().any():
            count = int(dataframe[column].isna().sum())
            raise BuildError(f"{context}: {count} NULL value(s) in required column {column!r}")


def attach_equipment_fk(
    dataframe: pd.DataFrame,
    model_map: Mapping[str, int],
    context: str,
) -> pd.DataFrame:
    """Attach a validated equipment_model_id foreign key."""
    result = dataframe.copy()
    if "system_model" not in result.columns:
        raise BuildError(f"{context}: missing system_model column")

    unknown = sorted(
        set(result["system_model"].dropna().astype(str)) - set(model_map)
    )
    if unknown:
        raise BuildError(f"{context}: unknown system_model value(s): {unknown}")

    if result["system_model"].isna().any():
        raise BuildError(f"{context}: system_model contains NULL values")

    result["equipment_model_id"] = (
        result["system_model"].map(model_map).astype("int64")
    )
    return result


def _linhas(dataframe: pd.DataFrame, colunas: Sequence[str]) -> list[dict]:
    """Linhas (dicts) das colunas pedidas, com NaN -> None e escalares do Python."""
    selecionado = dataframe[list(colunas)].astype(object)
    selecionado = selecionado.where(selecionado.notna(), None)
    return selecionado.to_dict(orient="records")


def _com_id(linhas: list[dict]) -> list[dict]:
    """Numera as linhas de 1 em diante (o autoincremento do banco antigo)."""
    return [{"id": numero, **linha} for numero, linha in enumerate(linhas, start=1)]


def _ler_filhas(
    qdmt_workbook: Path,
    aba: str,
    colunas_exigidas: Sequence[str],
    colunas: Sequence[str],
    ids_por_modelo: dict[str, int],
    contexto: str,
    extras: dict | None = None,
    com_pagina_fonte: bool = False,
) -> list[dict]:
    """Lê uma aba filha, valida o modelo (FK) e devolve as linhas com id."""
    dataframe = read_sheet(qdmt_workbook, aba, colunas_exigidas)
    colunas = list(colunas)
    if com_pagina_fonte and "source_page" in dataframe.columns:
        colunas.append("source_page")
    for coluna, valor in (extras or {}).items():
        dataframe[coluna] = valor
        colunas.append(coluna)
    anexado = attach_equipment_fk(dataframe, ids_por_modelo, contexto)
    if anexado["equipment_model_id"].isna().any():
        raise BuildError(f"{contexto}: NULL equipment_model_id after model mapping")
    return _com_id(_linhas(anexado, colunas))


def ler_qdmt(xlsx: Path) -> TabelasFamilia:
    """Lê a planilha QDMT e devolve equipment_model, airflow_point, cooling_performance,
    heating_performance e sound_level (colunas antigas, com `id`), sem gravar nada."""
    qdmt_workbook = Path(xlsx)
    dataframe = read_sheet(
        qdmt_workbook,
        "Equipment_Models",
        [
            "system_model",
            "nominal_kbtu",
            "indoor_model",
            "outdoor_model",
            "cooling_btuh",
            "cooling_input_w",
            "cooling_current_a",
            "heating_btuh",
            "max_esp_inwg",
            "indoor_weight_kg",
            "indoor_dims_mm",
            "power_supply",
        ],
    ).rename(
        columns={
            "nominal_kbtu": "nominal_class_kbtu",
            "cooling_btuh": "rated_cooling_btuh",
            "cooling_input_w": "rated_cooling_input_w",
            "heating_btuh": "rated_heating_btuh",
            "indoor_dims_mm": "indoor_dimensions_mm",
            "outdoor_dims_mm": "outdoor_dimensions_mm",
        }
    )

    assert_unique_values(dataframe, "system_model", "Equipment_Models")
    assert_no_nulls(
        dataframe,
        [
            "system_model",
            "nominal_class_kbtu",
            "indoor_model",
            "outdoor_model",
            "rated_cooling_btuh",
            "rated_cooling_input_w",
            "cooling_current_a",
            "max_esp_inwg",
            "indoor_weight_kg",
            "indoor_dimensions_mm",
            "power_supply",
        ],
        "Equipment_Models",
    )

    allowed_columns = [
        "system_model",
        "nominal_class_kbtu",
        "indoor_model",
        "outdoor_model",
        "rated_cooling_btuh",
        "rated_cooling_input_w",
        "cooling_current_a",
        "rated_heating_btuh",
        "eer_btu_wh",
        "eer_ww",
        "cop_ww",
        "max_esp_inwg",
        "indoor_weight_kg",
        "indoor_dimensions_mm",
        "power_supply",
        "compressor_type",
        "refrigerant_type",
        "outdoor_sound_dba",
        "outdoor_dimensions_mm",
        "outdoor_weight_kg",
        "pipe_liquid_inch",
        "pipe_gas_inch",
        "max_pipe_length_m",
        "max_height_diff_m",
        "drain_hose_mm",
        "nominal_airflow_cfm",
        "nominal_airflow_m3h",
        "indoor_sound_dba",
        "heating_input_w",
        "heating_current_a",
    ]
    dataframe = dataframe.reindex(columns=allowed_columns)

    modelos = _com_id(_linhas(dataframe, allowed_columns))
    ids_por_modelo = {str(m["system_model"]): m["id"] for m in modelos}
    LOGGER.info("equipment_model: %d rows", len(modelos))

    airflow = _ler_filhas(
        qdmt_workbook,
        "Airflow",
        ["system_model", "fan_speed", "esp_inwg", "esp_pa", "airflow_cfm", "airflow_m3h"],
        ["equipment_model_id", "fan_speed", "esp_inwg", "esp_pa", "airflow_cfm", "airflow_m3h"],
        ids_por_modelo,
        "Airflow",
    )

    colunas_resfriamento = [
        "equipment_model_id",
        "esp_inwg",
        "fan_speed",
        "airflow_cfm",
        "indoor_db_c",
        "indoor_wb_c",
        "outdoor_db_c",
        "total_capacity_btuh",
        "sensible_capacity_btuh",
        "input_w",
    ]
    exigidas_resfriamento = ["system_model"] + colunas_resfriamento[1:]
    cooling = _ler_filhas(
        qdmt_workbook,
        "Cooling_Performance",
        exigidas_resfriamento,
        colunas_resfriamento,
        ids_por_modelo,
        "Cooling_Performance",
        extras={"is_anomaly": 0},
        com_pagina_fonte=True,
    )

    colunas_aquecimento = [
        "equipment_model_id",
        "esp_inwg",
        "fan_speed",
        "airflow_cfm",
        "indoor_db_c",
        "outdoor_condition",
        "total_capacity_btuh",
        "input_w",
    ]
    exigidas_aquecimento = ["system_model"] + colunas_aquecimento[1:]
    heating = _ler_filhas(
        qdmt_workbook,
        "Heating_Performance",
        exigidas_aquecimento,
        colunas_aquecimento,
        ids_por_modelo,
        "Heating_Performance",
        com_pagina_fonte=True,
    )

    sound = _ler_filhas(
        qdmt_workbook,
        "Sound_Level",
        ["system_model", "fan_speed", "esp_inwg", "esp_pa", "sound_dba"],
        ["equipment_model_id", "fan_speed", "esp_inwg", "esp_pa", "sound_dba"],
        ids_por_modelo,
        "Sound_Level",
    )

    return {
        "equipment_model": modelos,
        "airflow_point": airflow,
        "cooling_performance": cooling,
        "heating_performance": heating,
        "sound_level": sound,
    }
