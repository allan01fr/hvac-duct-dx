"""Conversões métricas ↔ imperiais usadas pelos difusores (movido de diffuser_calculator.py)."""
from __future__ import annotations


def m_to_ft(x: float) -> float:
    return x / 0.3048


def ft_to_m(x: float) -> float:
    return x * 0.3048


def m2_to_ft2(area_m2: float) -> float:
    return area_m2 / (0.3048 ** 2)


def ft2_to_m2(area_ft2: float) -> float:
    return area_ft2 * (0.3048 ** 2)
