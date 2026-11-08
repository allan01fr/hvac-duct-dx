# Executa o motor de seleção para um caso e devolve linhas + avisos.
import json
import shutil
import sqlite3
from pathlib import Path

from casos_selecao import caso_completo

from ductdx.catalogo.consultas import abrir_catalogo
from ductdx.selecao import ParametrosForro, Requisitos, selecionar

RAIZ = Path(__file__).resolve().parents[2]

CAMPOS_LINHA = ("adequado", "pontuacao", "modelo", "classe_kbtu",
                "capacidade_total_btuh", "capacidade_sensivel_btuh", "vazao_cfm",
                "alimentacao", "modelo_interno", "modelo_externo",
                "dimensoes_internas_mm", "ruido_dba", "velocidade",
                "capacidade_aquecimento_btuh", "motivos", "catalogo",
                "eer_btu_wh", "metadados_vazao")


def preparar_banco(variante: str, destino: Path) -> Path:
    shutil.copy(RAIZ / "hvac_equipment.sqlite", destino)
    if variante == "padrao":
        return destino
    con = sqlite3.connect(destino)
    if variante == "sem_pontos_12_718":
        con.execute(
            "DELETE FROM ponto_desempenho WHERE tipo IN ('vazao', 'resfriamento') AND modelo_id = "
            "(SELECT m.id FROM modelo_equipamento m JOIN familia f ON f.id = m.familia_id "
            "WHERE f.codigo = 'qdmt' AND m.modelo_sistema = '53QDMT12-718')")
    else:
        raise ValueError(variante)
    con.commit()
    con.close()
    return destino


def executar_motor(caso: dict, banco: Path) -> dict:
    c = caso_completo(caso)
    margem_cap, margem_sens, margem_vazao = c["margens"]
    req = Requisitos(
        carga_total_btuh=c["total"], carga_sensivel_btuh=c["sensivel"],
        vazao_cfm=c["vazao"], esp_inwg=c["esp"], carga_aquecimento_btuh=c["aquecimento"],
        margem_capacidade_pct=margem_cap, margem_sensivel_pct=margem_sens,
        margem_vazao_pct=margem_vazao, temperatura_externa_c=int(c["temperatura"]),
        velocidade=c["velocidade"], fase=c["fase"], ruido_max_dba=float(c["ruido_max"]),
        forro=ParametrosForro(vao_mm=c["forro_vao"], folga_mm=c["forro_folga"],
                              dreno_m=c["forro_dreno"],
                              reprovar_se_nao_cabe=c["forro_reprovar"]))
    familia = c["familia"]
    catalogo = abrir_catalogo(banco)
    try:
        resultado = selecionar(catalogo, req, [familia] if familia else None)
    finally:
        catalogo.conn.close()
    linhas = [dict(zip(CAMPOS_LINHA, l.como_linha_legada())) for l in resultado.linhas]
    return json.loads(json.dumps({"linhas": linhas, "avisos": resultado.avisos}))
