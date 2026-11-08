# Consultas do motor ao esquema único: desempates, versão e mensagens de banco inválido.
import shutil
import sqlite3
from pathlib import Path

import pytest

from ductdx.catalogo.consultas import abrir_catalogo
from ductdx.selecao import (
    CatalogoIndisponivel,
    Requisitos,
    familia_por_codigo,
    selecionar,
)

RAIZ = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def catalogo():
    banco = RAIZ / "hvac_equipment.sqlite"
    if not banco.exists():
        pytest.skip("hvac_equipment.sqlite ausente")
    cat = abrir_catalogo(banco)
    yield cat
    cat.conn.close()


def test_aquecimento_qdmt_escolhe_menor_bs_interno_no_empate(catalogo):
    qdmt = familia_por_codigo("qdmt")
    m = next(x for x in catalogo.modelos(qdmt) if x.modelo == "53QDMT12-718")
    assert catalogo.capacidade_aquecimento_btuh(qdmt, m, "High", 0.16) == 10740


def test_modelos_empatados_saem_na_ordem_de_origem(catalogo):
    nomes = [m.modelo for m in catalogo.modelos(familia_por_codigo("qdmt"))]
    assert nomes.index("53QDMT30-718") + 1 == nomes.index("53QDMT30-708")


def test_banco_v1_da_mensagem_clara():
    with pytest.raises(CatalogoIndisponivel, match="python build_db.py"):
        abrir_catalogo(RAIZ / "tests/caracterizacao/dados/hvac_equipment_v1.sqlite")


def test_banco_ausente_da_mensagem_clara(tmp_path):
    with pytest.raises(CatalogoIndisponivel, match="python build_db.py"):
        abrir_catalogo(tmp_path / "nao.sqlite")


def test_banco_que_nao_e_sqlite_da_mensagem_clara(tmp_path):
    lixo = tmp_path / "lixo.sqlite"
    lixo.write_text("isto não é um banco")
    with pytest.raises(CatalogoIndisponivel, match="python build_db.py"):
        abrir_catalogo(lixo)


def test_versao_catalogo_no_resultado(catalogo):
    r = selecionar(catalogo, Requisitos(24000, 18000, 800, 0.16), ["qdmt"])
    assert r.versao_catalogo and len(r.versao_catalogo) == 64


def test_versao_vem_do_metadata(catalogo):
    with sqlite3.connect(RAIZ / "hvac_equipment.sqlite") as con:
        esperado = con.execute(
            "SELECT value FROM _metadata WHERE key = 'catalogo_sha256'").fetchone()[0]
    assert catalogo.versao() == esperado


def test_rooftop_sem_ruido_publicado_devolve_zero_sem_falhar(tmp_path):
    banco = tmp_path / "catalogo.sqlite"
    shutil.copy(RAIZ / "hvac_equipment.sqlite", banco)
    con = sqlite3.connect(banco)
    try:
        con.execute("""
            DELETE FROM ponto_desempenho WHERE tipo = 'ruido' AND modelo_id IN (
                SELECT m.id FROM modelo_equipamento m JOIN familia f ON f.id = m.familia_id
                WHERE f.codigo = 'rooftop')""")
        con.commit()
        restantes = con.execute("""
            SELECT COUNT(*) FROM ponto_desempenho p
            JOIN modelo_equipamento m ON m.id = p.modelo_id
            JOIN familia f ON f.id = m.familia_id
            WHERE f.codigo = 'rooftop' AND p.tipo = 'ruido'""").fetchone()[0]
    finally:
        con.close()
    assert restantes == 0

    rooftop = familia_por_codigo("rooftop")
    catalogo = abrir_catalogo(banco)
    try:
        r = selecionar(catalogo, Requisitos(180000, 130000, 6000, 0.8), ["rooftop"])
    finally:
        catalogo.conn.close()

    assert r.avisos == []
    assert r.versao_catalogo and len(r.versao_catalogo) == 64
    assert r.linhas and all(l.catalogo == rooftop.rotulo for l in r.linhas)
    assert any(l.adequado for l in r.linhas)
    assert all(l.ruido_dba == 0 for l in r.linhas)
