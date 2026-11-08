"""Famílias de catálogo: código, rótulo da GUI e prefixo das tabelas antigas."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Familia:
    codigo: str          # "qdmt" | "miraco" | "rooftop"
    rotulo: str          # texto exato de App.CATALOGS (com travessão "–")
    prefixo_legado: str  # "" | "miraco_" | "rooftop_"


FAMILIAS = (
    Familia("qdmt", "QDMT Duct Split (12–60 kBTU)", ""),
    Familia("miraco", "Miraco 50UB/38BB/40AB (55–300 MBH)", "miraco_"),
    Familia("rooftop", "Carrier Rooftops 50TFF/50TJS/50TJ (5–25 Ton)", "rooftop_"),
)


def familia_por_codigo(codigo: str) -> Familia:
    for familia in FAMILIAS:
        if familia.codigo == codigo:
            return familia
    raise ValueError(f"família desconhecida: {codigo!r}")


def familia_por_rotulo(rotulo: str) -> Familia:
    for familia in FAMILIAS:
        if familia.rotulo == rotulo:
            return familia
    raise ValueError(f"rótulo de família desconhecido: {rotulo!r}")
