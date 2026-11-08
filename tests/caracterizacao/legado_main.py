# Carrega, por AST, os métodos de busca do App legado (main.py) sem importar Qt.
import ast
import logging
import sqlite3
import types
from pathlib import Path

import report_builder

RAIZ = Path(__file__).resolve().parents[2]
METODOS = {"search", "_search_family", "_resolve_fan_speed",
           "_available_speeds", "_anomaly_filter", "_ceiling_params"}

def carregar_busca_legada() -> type:
    arvore = ast.parse((RAIZ / "main.py").read_text(encoding="utf-8"))
    app = next(n for n in arvore.body if isinstance(n, ast.ClassDef) and n.name == "App")
    corpo = [n for n in app.body
             if (isinstance(n, ast.FunctionDef) and n.name in METODOS)
             or (isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "CATALOGS")]
    classe = ast.ClassDef(name="BuscaLegada", bases=[], keywords=[], body=corpo, decorator_list=[])
    ns = {"report_builder": report_builder, "sqlite3": sqlite3, "logging": logging,
          "ui_shell": types.SimpleNamespace(refresh_stale_banner=lambda app: None)}
    exec(compile(ast.fix_missing_locations(ast.Module([classe], [])), "main.py", "exec"), ns)  # noqa: S102 - carga controlada do main.py do repo
    return ns["BuscaLegada"]


NOMES_ESP = {"ESPInput", "ESPResult", "calculate_esp", "suggest_esp_from_cfm"}
CONSTANTES_ESP = {"ESP_PRESETS", "ACCESSORIES_PRESSURE", "FITTINGS_PRESSURE", "FRICTION_PER_METER"}

def carregar_esp() -> dict:
    """Extrai, por AST, o cálculo de ESP do nível de módulo de main.py."""
    arvore = ast.parse((RAIZ / "main.py").read_text(encoding="utf-8"))
    corpo = [n for n in arvore.body
             if (isinstance(n, ast.ClassDef | ast.FunctionDef) and n.name in NOMES_ESP)
             or (isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") in CONSTANTES_ESP)]
    ns = {}
    exec("from dataclasses import dataclass, field", ns)  # noqa: S102 - import fixo
    exec(compile(ast.Module(corpo, []), "main.py", "exec"), ns)  # noqa: S102 - carga controlada do main.py do repo
    return {k: ns[k] for k in sorted(NOMES_ESP | CONSTANTES_ESP)}
