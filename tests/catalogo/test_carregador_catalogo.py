# Carregador único: constrói o banco v2 a partir das fontes e reproduz o v1 pelas visões.
import sqlite3
from pathlib import Path

import pytest

from ductdx.catalogo.carregador import construir_banco
from ductdx.catalogo.esquema import COLUNAS_LEGADAS
from ductdx.selecao.familias import FAMILIAS

RAIZ = Path(__file__).resolve().parents[2]
DADOS = RAIZ / "data"
BANCO_V1 = RAIZ / "tests" / "caracterizacao" / "dados" / "hvac_equipment_v1.sqlite"

# O v1 foi gerado antes da correção da planilha do 718 (commit 1fa5f7a): nestas colunas ele guarda NULL.
COLUNAS_718_ATUALIZADAS = {
    "compressor_type", "refrigerant_type", "outdoor_sound_dba", "outdoor_dimensions_mm",
    "outdoor_weight_kg", "pipe_liquid_inch", "pipe_gas_inch", "max_pipe_length_m",
    "max_height_diff_m", "drain_hose_mm", "nominal_airflow_cfm", "nominal_airflow_m3h",
    "indoor_sound_dba", "heating_input_w", "heating_current_a",
}


@pytest.fixture(scope="module")
def banco_novo(tmp_path_factory):
    return construir_banco(DADOS, tmp_path_factory.mktemp("b") / "hvac.sqlite")


def _normalizar(valor):
    if isinstance(valor, str):
        try:
            return float(valor.replace(",", ""))
        except ValueError:
            return valor
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        return float(valor)
    return valor


def _ler(banco, tabela):
    with sqlite3.connect(banco) as conn:
        conn.row_factory = sqlite3.Row
        return [{k: _normalizar(v) for k, v in dict(r).items()}
                for r in conn.execute(f"SELECT * FROM {tabela}")]


def test_visoes_do_banco_novo_reproduzem_o_v1(banco_novo):
    assert len(COLUNAS_LEGADAS) == 16
    for (codigo, tabela) in COLUNAS_LEGADAS:
        prefixo = next(f.prefixo_legado for f in FAMILIAS if f.codigo == codigo)
        nome = prefixo + tabela
        novo, antigo = _ler(banco_novo, nome), _ler(BANCO_V1, nome)
        assert len(novo) == len(antigo), nome
        for numero, (n, a) in enumerate(zip(novo, antigo, strict=True)):
            assert list(n) == list(a), nome
            diferentes = {c for c in a if n[c] != a[c]}
            if nome == "equipment_model" and a["system_model"] == "53QDMT30-718":
                assert diferentes == COLUNAS_718_ATUALIZADAS
            else:
                assert diferentes == set(), f"{nome}, linha {numero}: {diferentes}"


def test_construcao_e_reprodutivel(tmp_path):
    a = construir_banco(DADOS, tmp_path / "a.sqlite")
    b = construir_banco(DADOS, tmp_path / "b.sqlite")
    for tabela in ("fabricante", "familia", "modelo_equipamento", "ponto_desempenho"):
        assert _ler(a, tabela) == _ler(b, tabela), tabela
    meta_a = {m["key"]: m["value"] for m in _ler(a, "_metadata")}
    meta_b = {m["key"]: m["value"] for m in _ler(b, "_metadata")}
    meta_a.pop("build_timestamp_utc"), meta_b.pop("build_timestamp_utc")
    assert meta_a == meta_b


def test_contagens_por_familia(banco_novo):
    sql_modelos = ("SELECT COUNT(*) FROM modelo_equipamento m JOIN familia f ON f.id = m.familia_id "
                   "WHERE f.codigo = ?")
    sql_pontos = ("SELECT p.tipo, COUNT(*) FROM ponto_desempenho p "
                  "JOIN modelo_equipamento m ON m.id = p.modelo_id "
                  "JOIN familia f ON f.id = m.familia_id WHERE f.codigo = ? GROUP BY p.tipo")
    esperado = {
        "qdmt": (9, {"vazao": 211, "resfriamento": 2976, "aquecimento": 1674, "ruido": 210}),
        "miraco": (14, {"vazao": 14, "resfriamento": 84, "aquecimento": 7, "ruido": 14}),
        "rooftop": (14, {"vazao": 192, "resfriamento": 768, "ruido": 14}),
    }
    with sqlite3.connect(banco_novo) as conn:
        for codigo, (modelos, pontos) in esperado.items():
            assert conn.execute(sql_modelos, (codigo,)).fetchone()[0] == modelos
            assert dict(conn.execute(sql_pontos, (codigo,)).fetchall()) == pontos


def test_bases_dos_ids_de_origem(banco_novo):
    # A visão devolve id_origem como o id do v1: QDMT conta de 1, miraco e rooftop de 0.
    sql = ("SELECT MIN(m.id_origem), MAX(m.id_origem) FROM modelo_equipamento m "
           "JOIN familia f ON f.id = m.familia_id WHERE f.codigo = ?")
    with sqlite3.connect(banco_novo) as conn:
        assert conn.execute(sql, ("qdmt",)).fetchone() == (1, 9)
        assert conn.execute(sql, ("miraco",)).fetchone() == (0, 13)
        assert conn.execute(sql, ("rooftop",)).fetchone() == (0, 13)


def test_metadados_origem_manual_e_integridade(banco_novo):
    with sqlite3.connect(banco_novo) as conn:
        meta = dict(conn.execute("SELECT key, value FROM _metadata"))
        assert meta["schema_version"] == "2"
        assert meta["catalogo_sha256"]
        assert sum(k.startswith("sha256:") for k in meta) >= 3
        manuais = conn.execute("SELECT modelo_sistema FROM modelo_equipamento "
                               "WHERE origem_dado = 'manual'").fetchall()
        assert manuais == [("53QDMT30-708",)]
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("SELECT nome FROM fabricante").fetchall() == [("Carrier",)]
        assert [r[0] for r in conn.execute("SELECT codigo FROM familia ORDER BY ordem")] == \
            [f.codigo for f in FAMILIAS]


def test_fonte_ausente_falha_com_caminho(tmp_path):
    with pytest.raises(FileNotFoundError, match="Carrier_Miraco"):
        construir_banco(tmp_path, tmp_path / "x.sqlite")
    assert not (tmp_path / "x.sqlite").exists()
