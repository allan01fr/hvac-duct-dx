# Executa a seleção legada (main.py via AST) para um caso e devolve linhas + avisos.
import json
import shutil
import sqlite3
from pathlib import Path

from casos_selecao import caso_completo
from legado_main import RAIZ, carregar_busca_legada

CAMPOS_LINHA = ("adequado", "pontuacao", "modelo", "classe_kbtu",
                "capacidade_total_btuh", "capacidade_sensivel_btuh", "vazao_cfm",
                "alimentacao", "modelo_interno", "modelo_externo",
                "dimensoes_internas_mm", "ruido_dba", "velocidade",
                "capacidade_aquecimento_btuh", "motivos", "catalogo",
                "eer_btu_wh", "metadados_vazao")

_FAMILIAS = {None: "All Catalogs", "qdmt": 1, "miraco": 2, "rooftop": 3}
_FASES = {"qualquer": "Any", "monofasico": "1-Phase (220-240V)",
          "trifasico": "3-Phase (380-420V)"}


def preparar_banco(variante: str, destino: Path) -> Path:
    shutil.copy(RAIZ / "hvac_equipment.sqlite", destino)
    if variante == "padrao":
        return destino
    con = sqlite3.connect(destino)
    if variante == "sem_pontos_12_718":
        mid = con.execute(
            "SELECT id FROM equipment_model WHERE system_model='53QDMT12-718'"
        ).fetchone()[0]
        for tabela in ("airflow_point", "cooling_performance"):
            con.execute(f"DELETE FROM {tabela} WHERE equipment_model_id=?", (mid,))
    elif variante == "sem_tabela_ruido_rooftop":
        con.execute("DROP TABLE rooftop_sound_level")
    else:
        raise ValueError(variante)
    con.commit()
    con.close()
    return destino


class _Widget:
    def __init__(self, valor):
        self.valor = valor
    def text(self):
        return str(self.valor)
    def value(self):
        return self.valor
    def currentText(self):
        return str(self.valor)
    def isChecked(self):
        return bool(self.valor)
    def setText(self, texto):
        self.valor = texto
    def __getattr__(self, nome):  # clearContents, setRowCount, setEnabled, setStyleSheet...
        return lambda *a, **k: None


def executar_legado(caso: dict, banco: Path) -> dict:
    c = caso_completo(caso)
    classe = carregar_busca_legada()
    app = classe()
    app.conn = sqlite3.connect(banco)
    app._speed_cache = {}
    app.cart = []
    familia = c["familia"]
    app.catalog_family = _Widget(
        "All Catalogs" if familia is None else app.CATALOGS[_FAMILIAS[familia]][0])
    app.btu, app.sens, app.cfm, app.esp = (
        _Widget(c["total"]), _Widget(c["sensivel"]), _Widget(c["vazao"]), _Widget(c["esp"]))
    app.heat = _Widget(c["aquecimento"])
    app.capm, app.safm, app.afm = (_Widget(m) for m in c["margens"])
    app.outdoor_temp = _Widget(c["temperatura"])
    app.fan_speed = _Widget(c["velocidade"])
    app.phase = _Widget(_FASES[c["fase"]])
    app.max_sound = _Widget(c["ruido_max"])
    app.ceiling_void = _Widget(c["forro_vao"])
    app.ceiling_clear = _Widget(c["forro_folga"])
    app.drain_run = _Widget(c["forro_dreno"])
    app.ceiling_enforce = _Widget(c["forro_reprovar"])
    app.best_match_only = _Widget(False)
    app.status = _Widget("")
    app.export, app.table, app.summary = _Widget(""), _Widget(""), _Widget("")
    capturado = []
    app.render = lambda rows, *a, **k: capturado.extend(rows)
    app.search()
    avisos = [a for a in app.status.valor.split("; ") if a]
    app.conn.close()
    linhas = [dict(zip(CAMPOS_LINHA, linha)) for linha in capturado]
    return json.loads(json.dumps({"linhas": linhas, "avisos": avisos}))
