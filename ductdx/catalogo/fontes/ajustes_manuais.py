"""Ajustes manuais do QDMT: modelos informados pelo usuário em `manual_unit_overrides.json`.

O modelo manual entra com `id` = maior id + 1 e os pontos de vazão com `id` = maior
id de `airflow_point` + 1. Os valores que a especificação do usuário não traz são
declarados no próprio JSON (`inherited_from` / `inherited_fields`), nunca inferidos aqui.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from ductdx.catalogo.fontes import TabelasFamilia

# Constantes atuais, iguais às de rooftop_loader.py (a Tarefa 15 as troca).
PA_POR_INWG = 249.0889
M3H_POR_CFM = 1.69901

# Campos do JSON que são colunas de equipment_model com o mesmo nome.
_CAMPOS_DO_MODELO = (
    "system_model", "indoor_model", "outdoor_model", "nominal_class_kbtu",
    "rated_cooling_btuh", "power_supply", "max_esp_inwg", "pipe_gas_inch", "pipe_liquid_inch",
)


def _maior_id(linhas: list[dict]) -> int:
    return max((linha["id"] for linha in linhas), default=0)


def aplicar_ajustes_manuais(qdmt: TabelasFamilia, json_path: Path) -> TabelasFamilia:
    """Devolve uma cópia de `qdmt` com os modelos e pontos de vazão do JSON acrescentados."""
    tabelas = copy.deepcopy(qdmt)
    especificacoes = json.loads(Path(json_path).read_text(encoding="utf-8"))
    colunas = list(tabelas["equipment_model"][0])

    for especificacao in especificacoes:
        modelo_id = _maior_id(tabelas["equipment_model"]) + 1
        modelo = dict.fromkeys(colunas)
        modelo["id"] = modelo_id
        for campo in _CAMPOS_DO_MODELO:
            modelo[campo] = especificacao[campo]
        for campo, valor in especificacao.get("inherited_fields", {}).items():
            if campo not in modelo:
                raise KeyError(f"Campo herdado desconhecido: {campo!r}")
            modelo[campo] = valor
        tabelas["equipment_model"].append(modelo)

        for ponto in especificacao["airflow_points"]:
            tabelas["airflow_point"].append({
                "id": _maior_id(tabelas["airflow_point"]) + 1,
                "equipment_model_id": modelo_id,
                "fan_speed": ponto["fan_speed"],
                "esp_inwg": ponto["esp_inwg"],
                "esp_pa": round(ponto["esp_inwg"] * PA_POR_INWG),
                "airflow_cfm": ponto["airflow_cfm"],
                "airflow_m3h": round(ponto["airflow_cfm"] * M3H_POR_CFM),
            })
    return tabelas
