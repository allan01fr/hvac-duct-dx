"""Consultas do motor de seleção ao catálogo no esquema único (versão 2)."""
import sqlite3
from pathlib import Path

from ductdx.catalogo.esquema import VERSAO_ESQUEMA
from ductdx.selecao.catalogo import (
    CatalogoIndisponivel,
    ModeloCatalogo,
    PontoResfriamento,
    PontoVazao,
)
from ductdx.selecao.familias import Familia

# Busca conservadora: prefere o primeiro ponto do catálogo IGUAL OU ACIMA do valor de
# projeto (ESP maior / ar externo mais quente = menos capacidade e vazão); só recua
# para o ponto abaixo mais próximo quando o catálogo não tem nada acima.
EPS = 1e-9

_ORDEM_ESP = "(esp_inwg < ?), ABS(esp_inwg - ?)"


class CatalogoUnificado:
    """Implementa Catalogo sobre o esquema único; versao() é o hash do catálogo."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self._cache_velocidades: dict[int, set[str]] = {}

    def versao(self) -> str | None:
        linha = self.conn.execute(
            "SELECT value FROM _metadata WHERE key = 'catalogo_sha256'").fetchone()
        return linha[0] if linha else None

    def modelos(self, familia: Familia) -> list[ModeloCatalogo]:
        linhas = self.conn.execute("""
            SELECT m.id, m.id_origem, m.modelo_sistema, m.classe_nominal_kbtu,
                   m.capacidade_resfriamento_btuh, m.esp_max_inwg, m.alimentacao,
                   m.modelo_interno, m.modelo_externo, m.dimensoes_internas_mm,
                   m.eer_btu_wh
            FROM modelo_equipamento m JOIN familia f ON f.id = m.familia_id
            WHERE f.codigo = ?
            ORDER BY m.classe_nominal_kbtu, m.id_origem
        """, (familia.codigo,)).fetchall()
        return [ModeloCatalogo(*linha) for linha in linhas]

    def velocidades(self, familia: Familia, modelo: ModeloCatalogo) -> set[str]:
        if modelo.id not in self._cache_velocidades:
            self._cache_velocidades[modelo.id] = {
                linha[0] for linha in self.conn.execute(
                    """SELECT DISTINCT velocidade FROM ponto_desempenho
                       WHERE modelo_id = ? AND tipo IN ('vazao', 'resfriamento')
                         AND velocidade IS NOT NULL""", (modelo.id,))
                if linha[0]}
        return self._cache_velocidades[modelo.id]

    def marca_anomalias(self, familia: Familia | None = None) -> bool:
        return True

    def ponto_resfriamento(self, familia: Familia, modelo: ModeloCatalogo, velocidade: str,
                           bs_externo_c: int, esp_inwg: float) -> PontoResfriamento | None:
        linha = self.conn.execute(
            """
            SELECT capacidade_total_btuh, capacidade_sensivel_btuh, esp_inwg
            FROM ponto_desempenho
            WHERE modelo_id = ? AND tipo = 'resfriamento' AND velocidade = ?
              AND bs_interno_c = 27 AND bu_interno_c = 19 AND anomalia = 0
            ORDER BY (bs_externo_c < ?), ABS(bs_externo_c - ?),
                     (esp_inwg < ?), ABS(esp_inwg - ?), ordem_origem
            LIMIT 1
            """,
            (modelo.id, velocidade, bs_externo_c - EPS, bs_externo_c,
             esp_inwg - EPS, esp_inwg),
        ).fetchone()
        return PontoResfriamento(*linha) if linha else None

    def tem_ponto_anomalo(self, familia: Familia, modelo: ModeloCatalogo, velocidade: str,
                          bs_externo_c: int) -> bool:
        return self.conn.execute(
            """
            SELECT 1 FROM ponto_desempenho
            WHERE modelo_id = ? AND tipo = 'resfriamento' AND velocidade = ?
              AND bs_interno_c = 27 AND bu_interno_c = 19 AND anomalia = 1
            ORDER BY (bs_externo_c < ?), ABS(bs_externo_c - ?), ordem_origem
            LIMIT 1
            """,
            (modelo.id, velocidade, bs_externo_c - EPS, bs_externo_c),
        ).fetchone() is not None

    def ponto_vazao(self, familia: Familia, modelo: ModeloCatalogo, velocidade: str,
                    esp_inwg: float) -> PontoVazao | None:
        linha = self.conn.execute(
            f"""
            SELECT esp_inwg, vazao_cfm FROM ponto_desempenho
            WHERE modelo_id = ? AND tipo = 'vazao' AND velocidade = ?
            ORDER BY {_ORDEM_ESP}, ordem_origem LIMIT 1
            """,
            (modelo.id, velocidade, esp_inwg - EPS, esp_inwg),
        ).fetchone()
        return PontoVazao(*linha) if linha else None

    def ruido_dba(self, familia: Familia, modelo: ModeloCatalogo, velocidade: str,
                  esp_inwg: float) -> float | None:
        linha = self.conn.execute(
            f"""
            SELECT ruido_dba FROM ponto_desempenho
            WHERE modelo_id = ? AND tipo = 'ruido' AND velocidade = ?
            ORDER BY {_ORDEM_ESP}, ordem_origem LIMIT 1
            """,
            (modelo.id, velocidade, esp_inwg - EPS, esp_inwg),
        ).fetchone()
        return linha[0] if linha else 0

    def capacidade_aquecimento_btuh(self, familia: Familia, modelo: ModeloCatalogo,
                                    velocidade: str, esp_inwg: float,
                                    condicao: str = "2/1°C") -> float | None:
        # bs_interno_c no desempate: no QDMT há pontos que só diferem pelo BS interno
        # (15/20/27 °C); escolhe-se o de 15 °C, como o código antigo.
        linha = self.conn.execute(
            f"""
            SELECT capacidade_total_btuh FROM ponto_desempenho
            WHERE modelo_id = ? AND tipo = 'aquecimento' AND velocidade = ?
              AND condicao_externa = ?
            ORDER BY {_ORDEM_ESP}, bs_interno_c, ordem_origem LIMIT 1
            """,
            (modelo.id, velocidade, condicao, esp_inwg - EPS, esp_inwg),
        ).fetchone()
        return linha[0] if linha else 0


def abrir_catalogo(caminho: Path) -> CatalogoUnificado:
    """Abre o banco; CatalogoIndisponivel se ausente ou fora do esquema versão 2."""
    caminho = Path(caminho)
    orientacao = "execute python build_db.py"
    if not caminho.exists():
        raise CatalogoIndisponivel(f"Banco do catálogo não encontrado: {caminho}; {orientacao}")
    conn = sqlite3.connect(caminho)
    try:
        linha = conn.execute(
            "SELECT value FROM _metadata WHERE key = 'schema_version'").fetchone()
    except sqlite3.DatabaseError:
        linha = None
    if linha is None or linha[0] != str(VERSAO_ESQUEMA):
        conn.close()
        raise CatalogoIndisponivel(
            f"Banco do catálogo em esquema antigo ou ilegível: {caminho}; {orientacao}")
    return CatalogoUnificado(conn)
