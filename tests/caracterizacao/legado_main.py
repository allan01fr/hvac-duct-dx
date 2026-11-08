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
