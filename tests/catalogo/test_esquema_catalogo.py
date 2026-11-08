# Esquema único do catálogo: colunas legadas, mapa, restrições e visões de compatibilidade.
import sqlite3
from pathlib import Path

import pytest

from ductdx.catalogo.esquema import (
    COLUNAS_LEGADAS,
    MAPA_COLUNAS,
    TIPO_POR_TABELA,
    VERSAO_ESQUEMA,
    criar_esquema,
    criar_visoes_compatibilidade,
)
from ductdx.selecao.familias import familia_por_codigo

BANCO_V1 = Path(__file__).resolve().parents[1] / "caracterizacao" / "dados" / "hvac_equipment_v1.sqlite"


@pytest.fixture
def conn_vazio():
    conn = sqlite3.connect(":memory:")
    criar_esquema(conn)
    yield conn
    conn.close()


def _nome_legado(codigo, tabela):
    return familia_por_codigo(codigo).prefixo_legado + tabela


def _insere_basico(conn):
    conn.execute("INSERT INTO fabricante VALUES (1, 'Teste')")
    conn.execute("INSERT INTO familia VALUES (1, 1, 'qdmt', 'Rótulo', '', 1)")
    conn.execute("INSERT INTO modelo_equipamento (id, familia_id, id_origem, modelo_sistema, "
                 "classe_nominal_kbtu, capacidade_resfriamento_btuh, alimentacao) "
                 "VALUES (1, 1, 7, 'M1', 12, 12000, '220V')")


def test_versao_do_esquema():
    assert VERSAO_ESQUEMA == 2


def test_colunas_legadas_iguais_ao_banco_v1():
    assert len(COLUNAS_LEGADAS) == 16
    v1 = sqlite3.connect(BANCO_V1)
    try:
        for (codigo, tabela), colunas in COLUNAS_LEGADAS.items():
            nome = _nome_legado(codigo, tabela)
            real = tuple(r[1] for r in v1.execute(f"PRAGMA table_info({nome})"))
            assert real == colunas, nome
    finally:
        v1.close()


def test_mapa_cobre_toda_coluna_legada():
    for (_, tabela), colunas in COLUNAS_LEGADAS.items():
        for coluna in colunas:
            if coluna in ("id", "equipment_model_id"):
                continue
            assert (tabela, coluna) in MAPA_COLUNAS, (tabela, coluna)


def test_mapa_aponta_para_colunas_que_existem(conn_vazio):
    modelo = {r[1] for r in conn_vazio.execute("PRAGMA table_info(modelo_equipamento)")}
    ponto = {r[1] for r in conn_vazio.execute("PRAGMA table_info(ponto_desempenho)")}
    for (tabela, _), nova in MAPA_COLUNAS.items():
        destino = ponto if tabela in TIPO_POR_TABELA else modelo
        assert nova in destino, (tabela, nova)


def test_chave_estrangeira_e_checks_valem(conn_vazio):
    _insere_basico(conn_vazio)
    with pytest.raises(sqlite3.IntegrityError):
        conn_vazio.execute("INSERT INTO ponto_desempenho (modelo_id, tipo, ordem_origem, vazao_cfm) "
                           "VALUES (99, 'vazao', 1, 400)")
    with pytest.raises(sqlite3.IntegrityError):
        conn_vazio.execute("INSERT INTO ponto_desempenho (modelo_id, tipo, ordem_origem) "
                           "VALUES (1, 'vazao', 1)")
    with pytest.raises(sqlite3.IntegrityError):
        conn_vazio.execute("INSERT INTO ponto_desempenho (modelo_id, tipo, ordem_origem, vazao_cfm) "
                           "VALUES (1, 'outro', 1, 400)")
    with pytest.raises(sqlite3.IntegrityError):
        conn_vazio.execute("INSERT INTO modelo_equipamento (familia_id, id_origem, modelo_sistema, "
                           "classe_nominal_kbtu, capacidade_resfriamento_btuh, alimentacao) "
                           "VALUES (1, 8, 'M2', 12, 0, '220V')")


def test_visoes_tem_nomes_e_colunas_antigas(conn_vazio):
    criar_visoes_compatibilidade(conn_vazio)
    for (codigo, tabela), colunas in COLUNAS_LEGADAS.items():
        nome = _nome_legado(codigo, tabela)
        cursor = conn_vazio.execute(f"SELECT * FROM {nome}")
        assert tuple(d[0] for d in cursor.description) == colunas


def test_visoes_devolvem_os_valores_antigos(conn_vazio):
    _insere_basico(conn_vazio)
    conn_vazio.execute("INSERT INTO ponto_desempenho (modelo_id, tipo, ordem_origem, velocidade, "
                       "vazao_cfm) VALUES (1, 'vazao', 42, 'High', 400)")
    criar_visoes_compatibilidade(conn_vazio)
    modelo = conn_vazio.execute("SELECT id, system_model FROM equipment_model").fetchall()
    assert modelo == [(7, "M1")]
    ponto = conn_vazio.execute("SELECT id, equipment_model_id, fan_speed, airflow_cfm "
                               "FROM airflow_point").fetchall()
    assert ponto == [(42, 7, "High", 400.0)]
    assert conn_vazio.execute("SELECT COUNT(*) FROM miraco_electrical_spec").fetchone() == (0,)
