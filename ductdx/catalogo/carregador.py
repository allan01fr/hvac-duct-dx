"""Carregador único do catálogo: lê as planilhas e grava o banco no esquema v2.

Uma só passagem: leitores (`ductdx.catalogo.fontes`) -> tabelas fabricante, familia,
modelo_equipamento e ponto_desempenho -> validações -> metadados -> visões de
compatibilidade. O banco é montado num arquivo temporário e só substitui o destino
(`os.replace`) quando tudo passou.
"""
from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from ductdx.catalogo.esquema import (
    MAPA_COLUNAS,
    TIPO_POR_TABELA,
    VERSAO_ESQUEMA,
    criar_esquema,
    criar_visoes_compatibilidade,
)
from ductdx.catalogo.fontes import TabelasFamilia
from ductdx.catalogo.fontes.ajustes_manuais import aplicar_ajustes_manuais
from ductdx.catalogo.fontes.miraco import ler_miraco
from ductdx.catalogo.fontes.qdmt import BuildError, ler_qdmt
from ductdx.catalogo.fontes.rooftop import ler_rooftop
from ductdx.selecao.familias import FAMILIAS

LOGGER = logging.getLogger(__name__)

FABRICANTE = "Carrier"
ARQUIVO_QDMT = "Ceiling Concealed Ducted Split Systems.xlsx"
ARQUIVO_MIRACO = "Carrier_Miraco_HVAC_Selection_Database_v3.xlsx"
ARQUIVOS_ROOFTOP = (
    "50TJS_Product_Catalog_Complete_Database_corrected(1).xlsx",
    "50TJProductData_extracted(1).xlsx",
    "50TFFProductData_reviewed.xlsx",
)
ARQUIVO_AJUSTES = "manual_unit_overrides.json"
# O ajuste manual só vale para o QDMT; o modelo que ele acrescenta é marcado 'manual'.
_FAMILIA_COM_AJUSTES = "qdmt"

_COLUNAS_VAZAO_TEXTO = ("nominal_airflow_cfm", "nominal_airflow_m3h")


def _fontes(pasta_dados: Path) -> dict[str, Path]:
    arquivos = (ARQUIVO_QDMT, ARQUIVO_MIRACO, *ARQUIVOS_ROOFTOP, ARQUIVO_AJUSTES)
    return {nome: pasta_dados / nome for nome in arquivos}


def _exigir_fontes(fontes: dict[str, Path]) -> None:
    ausentes = [str(caminho) for caminho in fontes.values() if not caminho.is_file()]
    if ausentes:
        raise FileNotFoundError("Fonte(s) do catálogo ausente(s): " + "; ".join(ausentes))


def _sha256(caminho: Path) -> str:
    resumo = hashlib.sha256()
    with caminho.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1 << 20), b""):
            resumo.update(bloco)
    return resumo.hexdigest()


def _carimbo() -> str:
    """Data do build; SOURCE_DATE_EPOCH torna o carimbo reprodutível."""
    epoca = os.environ.get("SOURCE_DATE_EPOCH")
    if epoca is not None:
        try:
            return datetime.fromtimestamp(int(epoca), tz=UTC).isoformat()
        except (TypeError, ValueError, OverflowError) as exc:
            raise BuildError("SOURCE_DATE_EPOCH must be a valid Unix timestamp") from exc
    return datetime.now(UTC).isoformat()


def _numero(valor):
    """Vazão nominal vinha como texto no v1 ('1,200'); no esquema novo é REAL."""
    if isinstance(valor, str):
        try:
            return float(valor.replace(",", ""))
        except ValueError:
            return valor
    return valor


def _gravar_familias(conn: sqlite3.Connection) -> dict[str, int]:
    conn.execute("INSERT INTO fabricante (id, nome) VALUES (1, ?)", (FABRICANTE,))
    ids = {}
    for ordem, familia in enumerate(FAMILIAS, start=1):
        conn.execute(
            "INSERT INTO familia (id, fabricante_id, codigo, rotulo, prefixo_legado, ordem) "
            "VALUES (?, 1, ?, ?, ?, ?)",
            (ordem, familia.codigo, familia.rotulo, familia.prefixo_legado, ordem))
        ids[familia.codigo] = ordem
    return ids


def _linha_modelo(modelo: dict, eletrica: dict | None, familia_id: int, manual: bool) -> dict:
    linha = {"familia_id": familia_id, "id_origem": modelo["id"],
             "origem_dado": "manual" if manual else "catalogo",
             "tem_especificacao_eletrica": 1 if eletrica is not None else 0}
    for antiga, valor in modelo.items():
        if antiga != "id":
            linha[MAPA_COLUNAS[("equipment_model", antiga)]] = (
                _numero(valor) if antiga in _COLUNAS_VAZAO_TEXTO else valor)
    for antiga, valor in (eletrica or {}).items():
        if antiga != "equipment_model_id":
            linha[MAPA_COLUNAS[("electrical_spec", antiga)]] = valor
    return linha


def _inserir(conn: sqlite3.Connection, tabela: str, linha: dict) -> int:
    colunas = ", ".join(linha)
    marcas = ", ".join("?" for _ in linha)
    cursor = conn.execute(f"INSERT INTO {tabela} ({colunas}) VALUES ({marcas})", tuple(linha.values()))
    return cursor.lastrowid


def _gravar_familia(conn: sqlite3.Connection, codigo: str, familia_id: int,
                    tabelas: TabelasFamilia, ids_manuais: frozenset = frozenset()) -> None:
    eletricas = {e["equipment_model_id"]: e for e in tabelas.get("electrical_spec", [])}
    modelo_por_origem = {}
    for modelo in tabelas["equipment_model"]:
        linha = _linha_modelo(modelo, eletricas.get(modelo["id"]), familia_id,
                              modelo["id"] in ids_manuais)
        modelo_por_origem[modelo["id"]] = _inserir(conn, "modelo_equipamento", linha)

    for tabela, tipo in TIPO_POR_TABELA.items():
        for posicao, ponto in enumerate(tabelas.get(tabela, []), start=1):
            linha = {"modelo_id": modelo_por_origem[ponto["equipment_model_id"]], "tipo": tipo,
                     "ordem_origem": ponto.get("id", posicao)}
            for antiga, valor in ponto.items():
                if antiga not in ("id", "equipment_model_id"):
                    linha[MAPA_COLUNAS[(tabela, antiga)]] = valor
            _inserir(conn, "ponto_desempenho", linha)
    LOGGER.info("%s: %d modelos", codigo, len(modelo_por_origem))


def _validar(conn: sqlite3.Connection) -> None:
    resultado = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if resultado != "ok":
        raise BuildError(f"integrity_check falhou: {resultado}")
    if conn.execute("PRAGMA foreign_key_check").fetchall():
        raise BuildError("foreign_key_check encontrou violações")
    for familia in FAMILIAS:
        n = conn.execute("SELECT COUNT(*) FROM modelo_equipamento m JOIN familia f "
                         "ON f.id = m.familia_id WHERE f.codigo = ?", (familia.codigo,)).fetchone()[0]
        if n < 1:
            raise BuildError(f"família {familia.codigo} sem modelos")
    sem_ponto = conn.execute(
        "SELECT modelo_sistema FROM modelo_equipamento m WHERE NOT EXISTS "
        "(SELECT 1 FROM ponto_desempenho p WHERE p.modelo_id = m.id)").fetchall()
    if sem_ponto:
        raise BuildError(f"modelos sem nenhum ponto de desempenho: {[r[0] for r in sem_ponto]}")


def _gravar_metadados(conn: sqlite3.Connection, fontes: dict[str, Path]) -> None:
    hashes = {nome: _sha256(caminho) for nome, caminho in fontes.items()}
    catalogo = hashlib.sha256("".join(sorted(hashes.values())).encode()).hexdigest()
    linhas = [("schema_version", str(VERSAO_ESQUEMA)), ("build_timestamp_utc", _carimbo())]
    linhas += [(f"sha256:{nome}", valor) for nome, valor in hashes.items()]
    linhas.append(("catalogo_sha256", catalogo))
    conn.executemany("INSERT INTO _metadata (key, value) VALUES (?, ?)", linhas)


def construir_banco(pasta_dados: Path, destino: Path) -> Path:
    """Constrói o banco v2 em `destino` (substituição atômica) e devolve o caminho."""
    pasta_dados, destino = Path(pasta_dados), Path(destino)
    fontes = _fontes(pasta_dados)
    _exigir_fontes(fontes)

    qdmt = ler_qdmt(fontes[ARQUIVO_QDMT])
    ids_antes = {m["id"] for m in qdmt["equipment_model"]}
    qdmt = aplicar_ajustes_manuais(qdmt, fontes[ARQUIVO_AJUSTES])
    ids_manuais = frozenset(m["id"] for m in qdmt["equipment_model"]) - ids_antes
    familias = {"qdmt": qdmt, "miraco": ler_miraco(fontes[ARQUIVO_MIRACO]),
                "rooftop": ler_rooftop(pasta_dados)}

    destino.parent.mkdir(parents=True, exist_ok=True)
    descritor, nome_temporario = tempfile.mkstemp(
        prefix=destino.name + ".", suffix=".tmp", dir=destino.parent)
    os.close(descritor)
    temporario = Path(nome_temporario)
    try:
        with closing(sqlite3.connect(temporario)) as conn:
            criar_esquema(conn)
            ids_familia = _gravar_familias(conn)
            for familia in FAMILIAS:
                manuais = ids_manuais if familia.codigo == _FAMILIA_COM_AJUSTES else frozenset()
                _gravar_familia(conn, familia.codigo, ids_familia[familia.codigo],
                                familias[familia.codigo], manuais)
            _validar(conn)
            _gravar_metadados(conn, fontes)
            criar_visoes_compatibilidade(conn)
            conn.commit()
        os.replace(temporario, destino)
    except BaseException:
        temporario.unlink(missing_ok=True)
        raise
    LOGGER.info("Banco gravado: %s", destino)
    return destino
