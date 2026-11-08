# Leitores das fontes do catálogo: reproduzem o banco v1 (exceto o que foi corrigido de propósito).
import json
import math
import sqlite3
from pathlib import Path

import pytest

from ductdx.catalogo.fontes.ajustes_manuais import aplicar_ajustes_manuais
from ductdx.catalogo.fontes.miraco import ler_miraco
from ductdx.catalogo.fontes.qdmt import ler_qdmt
from ductdx.catalogo.fontes.rooftop import ler_rooftop

RAIZ = Path(__file__).resolve().parents[2]
DADOS = RAIZ / "data"
BANCO_V1 = RAIZ / "tests" / "caracterizacao" / "dados" / "hvac_equipment_v1.sqlite"
XLSX_QDMT = DADOS / "Ceiling Concealed Ducted Split Systems.xlsx"
AJUSTES = DADOS / "manual_unit_overrides.json"

# A planilha do 718 foi corrigida (commit 1fa5f7a) sem regenerar o banco v1: no v1 estas colunas são NULL.
COLUNAS_718_ATUALIZADAS = {
    "compressor_type", "refrigerant_type", "outdoor_sound_dba", "outdoor_dimensions_mm",
    "outdoor_weight_kg", "pipe_liquid_inch", "pipe_gas_inch", "max_pipe_length_m",
    "max_height_diff_m", "drain_hose_mm", "nominal_airflow_cfm", "nominal_airflow_m3h",
    "indoor_sound_dba", "heating_input_w", "heating_current_a",
}


def normalizar(valor):
    """Texto numérico -> float, int -> float, NaN -> None (o v1 guarda números como texto)."""
    if valor is None or (isinstance(valor, float) and math.isnan(valor)):
        return None
    if isinstance(valor, bool):
        return float(valor)
    if isinstance(valor, (int, float)):
        return float(valor)
    if isinstance(valor, str):
        try:
            return float(valor.replace(",", ""))
        except ValueError:
            return valor
    return valor


def _linha_normalizada(linha):
    return {coluna: normalizar(valor) for coluna, valor in linha.items()}


def _linhas_v1(tabela, ordem="rowid"):
    with sqlite3.connect(BANCO_V1) as conn:
        conn.row_factory = sqlite3.Row
        return [_linha_normalizada(dict(r)) for r in conn.execute(f"SELECT * FROM {tabela} ORDER BY {ordem}")]


def _comparar(linhas, tabela_v1, ordem="rowid"):
    esperado = _linhas_v1(tabela_v1, ordem)
    obtido = [_linha_normalizada(l) for l in linhas]
    assert len(obtido) == len(esperado)
    assert set(obtido[0]) == set(esperado[0])
    for numero, (o, e) in enumerate(zip(obtido, esperado, strict=True)):
        assert o == e, f"{tabela_v1}, linha {numero}"


@pytest.fixture(scope="module")
def qdmt_com_ajustes():
    return aplicar_ajustes_manuais(ler_qdmt(XLSX_QDMT), AJUSTES)


def test_qdmt_com_ajustes_reproduz_o_v1_exceto_o_718_atualizado(qdmt_com_ajustes):
    for tabela in ("airflow_point", "cooling_performance", "heating_performance", "sound_level"):
        _comparar(qdmt_com_ajustes[tabela], tabela, "id")

    esperado = _linhas_v1("equipment_model", "id")
    obtido = [_linha_normalizada(l) for l in qdmt_com_ajustes["equipment_model"]]
    assert len(obtido) == len(esperado) == 9
    for o, e in zip(obtido, esperado, strict=True):
        assert set(o) == set(e)
        diferentes = {c for c in e if o[c] != e[c]}
        if e["system_model"] == "53QDMT30-718":
            assert diferentes == COLUNAS_718_ATUALIZADAS
            assert all(e[c] is None for c in diferentes)
        else:
            assert diferentes == set(), e["system_model"]


def test_miraco_reproduz_o_v1():
    tabelas = ler_miraco(DADOS / "Carrier_Miraco_HVAC_Selection_Database_v3.xlsx")
    assert set(tabelas) == {"equipment_model", "electrical_spec", "airflow_point",
                            "cooling_performance", "heating_performance", "sound_level"}
    for tabela, linhas in tabelas.items():
        _comparar(linhas, "miraco_" + tabela)


def test_rooftop_reproduz_o_v1():
    tabelas = ler_rooftop(DADOS)
    assert set(tabelas) == {"equipment_model", "cooling_performance", "airflow_point",
                            "sound_level", "electrical_spec"}
    for tabela, linhas in tabelas.items():
        _comparar(linhas, "rooftop_" + tabela)


def test_ajuste_manual_708_igual_ao_v1(qdmt_com_ajustes):
    modelos = {m["system_model"]: m for m in qdmt_com_ajustes["equipment_model"]}
    modelo = _linha_normalizada(modelos["53QDMT30-708"])
    assert modelo["id"] == 9.0
    esperado = next(e for e in _linhas_v1("equipment_model", "id") if e["id"] == 9.0)
    assert modelo == esperado
    ponto = qdmt_com_ajustes["airflow_point"][-1]
    assert (ponto["id"], ponto["equipment_model_id"], ponto["fan_speed"], ponto["esp_inwg"],
            ponto["esp_pa"], ponto["airflow_cfm"], ponto["airflow_m3h"]) == (211, 9, "High", 0.16, 40, 790, 1342)


def test_ajustes_nao_alteram_a_entrada_e_declaram_a_heranca():
    base = ler_qdmt(XLSX_QDMT)
    n_modelos, n_pontos = len(base["equipment_model"]), len(base["airflow_point"])
    aplicar_ajustes_manuais(base, AJUSTES)
    assert (len(base["equipment_model"]), len(base["airflow_point"])) == (n_modelos, n_pontos)
    especificacao = json.loads(AJUSTES.read_text(encoding="utf-8"))[0]
    assert especificacao["inherited_from"] == "53QDMT30-718"
    assert len(especificacao["inherited_fields"]) == 10
