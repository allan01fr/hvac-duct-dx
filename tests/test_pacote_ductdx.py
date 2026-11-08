# Pacote ductdx: instalável e importável sem GUI, pandas ou docx.
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PROIBIDOS = {"PySide6", "pandas", "docx"}
SUBPACOTES = ["ductdx", "ductdx.selecao", "ductdx.selecao.esp", "ductdx.selecao.forro",
              "ductdx.selecao.familias", "ductdx.selecao.requisitos", "ductdx.selecao.resultado",
              "ductdx.selecao.catalogo", "ductdx.selecao.motor",
              "ductdx.catalogo", "ductdx.catalogo.esquema", "ductdx.catalogo.consultas",
              "ductdx.difusores.geometria_ambiente", "ductdx.difusores.motor_posicionamento",
              "ductdx.difusores.adaptador_posicionamento", "ductdx.difusores.dados_catalogo"]   # ampliado nas Tarefas 9, 11 e 14
# ductdx.catalogo.fontes.* pode usar pandas/openpyxl (exceção à regra), por isso fica fora da lista acima.

def test_pacote_importa_sem_gui_nem_pandas():
    codigo = ("import importlib, sys\n"
              f"for m in {SUBPACOTES!r}: importlib.import_module(m)\n"
              f"print(sorted(m for m in sys.modules if m.split('.')[0] in {PROIBIDOS!r}))")
    saida = subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ,
                           capture_output=True, text=True, check=True).stdout.strip()
    assert saida == "[]"

def test_versao_unica():
    import tomllib

    import ductdx
    projeto = tomllib.loads((RAIZ / "pyproject.toml").read_text())["project"]
    assert projeto["dynamic"] == ["version"] and ductdx.__version__ == "0.1.0"

def test_report_builder_usa_a_mesma_verificacao_de_forro():
    import report_builder
    from ductdx.selecao import forro
    assert report_builder.check_ceiling_void is forro.check_ceiling_void
    assert report_builder.parse_dims("890x536x753") == (890.0, 536.0, 753.0)


def test_fontes_do_catalogo_usam_pandas_mas_nao_gui_nem_docx():
    codigo = ("import importlib, sys\n"
              "for m in ['ductdx.catalogo.fontes.qdmt', 'ductdx.catalogo.fontes.miraco',\n"
              "          'ductdx.catalogo.fontes.rooftop', 'ductdx.catalogo.fontes.ajustes_manuais',\n          'ductdx.catalogo.carregador']:\n"
              "    importlib.import_module(m)\n"
              "print(sorted(m for m in sys.modules if m.split('.')[0] in {'PySide6', 'docx'}))")
    saida = subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ,
                           capture_output=True, text=True, check=True).stdout.strip()
    assert saida == "[]"


def test_apelidos_da_raiz_sao_os_modulos_do_pacote():
    import catalog_data
    import placement_engine
    import placement_engine_adapter
    import room_geometry
    from ductdx.difusores import (
        adaptador_posicionamento,
        dados_catalogo,
        geometria_ambiente,
        motor_posicionamento,
    )
    assert (room_geometry, placement_engine, placement_engine_adapter, catalog_data) == (
        geometria_ambiente, motor_posicionamento, adaptador_posicionamento, dados_catalogo)
