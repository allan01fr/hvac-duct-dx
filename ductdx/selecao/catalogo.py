"""Interface entre o motor e o banco: o motor só fala com um Catalogo."""
from dataclasses import dataclass
from typing import Protocol

from ductdx.selecao.familias import Familia


class CatalogoIndisponivel(RuntimeError):
    """O catálogo não pode ser lido (banco ausente ou em esquema antigo)."""


@dataclass(frozen=True)
class ModeloCatalogo:
    id: int
    id_origem: int
    modelo: str
    classe_kbtu: float
    capacidade_nominal_btuh: float
    esp_max_inwg: float | None
    alimentacao: str
    modelo_interno: str
    modelo_externo: str
    dimensoes_internas_mm: str
    eer_btu_wh: float | None


@dataclass(frozen=True)
class PontoResfriamento:
    total_btuh: float
    sensivel_btuh: float
    esp_inwg: float | None


@dataclass(frozen=True)
class PontoVazao:
    esp_inwg: float | None
    vazao_cfm: float | None


class Catalogo(Protocol):
    def versao(self) -> str | None: ...

    def modelos(self, familia: Familia) -> list[ModeloCatalogo]: ...

    def velocidades(self, familia: Familia, modelo: ModeloCatalogo) -> set[str]: ...

    def marca_anomalias(self, familia: Familia) -> bool: ...

    def ponto_resfriamento(self, familia: Familia, modelo: ModeloCatalogo, velocidade: str,
                           bs_externo_c: int, esp_inwg: float) -> PontoResfriamento | None: ...

    def tem_ponto_anomalo(self, familia: Familia, modelo: ModeloCatalogo, velocidade: str,
                          bs_externo_c: int) -> bool: ...

    def ponto_vazao(self, familia: Familia, modelo: ModeloCatalogo, velocidade: str,
                    esp_inwg: float) -> PontoVazao | None: ...

    def ruido_dba(self, familia: Familia, modelo: ModeloCatalogo, velocidade: str,
                  esp_inwg: float) -> float | None: ...

    def capacidade_aquecimento_btuh(self, familia: Familia, modelo: ModeloCatalogo,
                                    velocidade: str, esp_inwg: float,
                                    condicao: str = "2/1°C") -> float | None: ...
