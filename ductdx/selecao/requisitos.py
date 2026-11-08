"""Entradas da seleção (Requisitos) e as grandezas já com margem (Requeridos)."""
import math
from dataclasses import dataclass, fields

from ductdx.selecao.forro import DEFAULT_CLEARANCE_MM

FASES = ("qualquer", "monofasico", "trifasico")
VELOCIDADES = ("High", "Medium", "Low", "Any")


def _exigir_numero_valido(nome: str, valor: float) -> None:
    if not math.isfinite(valor) or valor < 0:
        raise ValueError(f"{nome} deve ser um número finito e não negativo, recebi {valor!r}")


@dataclass(frozen=True)
class ParametrosForro:
    vao_mm: float = 0.0
    folga_mm: float = DEFAULT_CLEARANCE_MM
    dreno_m: float = 0.0
    reprovar_se_nao_cabe: bool = False

    def __post_init__(self) -> None:
        for nome in ("vao_mm", "folga_mm", "dreno_m"):
            _exigir_numero_valido(f"forro.{nome}", getattr(self, nome))


@dataclass(frozen=True)
class Requisitos:
    carga_total_btuh: float
    carga_sensivel_btuh: float
    vazao_cfm: float
    esp_inwg: float
    carga_aquecimento_btuh: float = 0.0
    margem_capacidade_pct: float = 10.0
    margem_sensivel_pct: float = 10.0
    margem_vazao_pct: float = 10.0
    temperatura_externa_c: int = 43
    velocidade: str = "High"
    fase: str = "qualquer"
    ruido_max_dba: float = 0.0
    forro: ParametrosForro = ParametrosForro()

    def __post_init__(self) -> None:
        for campo in fields(self):
            valor = getattr(self, campo.name)
            if isinstance(valor, (int, float)) and not isinstance(valor, bool):
                _exigir_numero_valido(campo.name, valor)
        if self.velocidade not in VELOCIDADES:
            raise ValueError(f"velocidade inválida: {self.velocidade!r}")
        if self.fase not in FASES:
            raise ValueError(f"fase inválida: {self.fase!r}")


@dataclass(frozen=True)
class Requeridos:
    total_btuh: float
    sensivel_btuh: float
    vazao_cfm: float
    aquecimento_btuh: float


def aplicar_margens(r: Requisitos) -> Requeridos:
    total = r.carga_total_btuh * (1 + r.margem_capacidade_pct / 100)
    sensivel = (r.carga_sensivel_btuh * (1 + r.margem_sensivel_pct / 100)
                if r.carga_sensivel_btuh > 0 else 0)
    vazao = r.vazao_cfm * (1 + r.margem_vazao_pct / 100)
    # peculiaridade mantida: o aquecimento usa a margem de capacidade
    cap_margin = 1 + r.margem_capacidade_pct / 100
    aquecimento = (r.carga_aquecimento_btuh * cap_margin
                   if r.carga_aquecimento_btuh > 0 else 0)
    return Requeridos(total, sensivel, vazao, aquecimento)


def temperatura_de_catalogo(temperatura_externa_c: float) -> int:
    return (35 if temperatura_externa_c <= 35
            else (43 if temperatura_externa_c <= 43
                  else (46 if temperatura_externa_c <= 46 else 52)))
