"""Entrada da seleção: ΔT, carga total, assinatura da seleção (movido de diffuser_calculator.py)."""
from __future__ import annotations

import math
import re

from ductdx.difusores.conversoes import ft_to_m
from ductdx.difusores.regras import calculate_supply_delta_t


def _resolve_delta_t(total_cfm: float, delta_t_f: float | None,
                     sensible_load_btuh: float | None) -> float | None:
    if delta_t_f is not None:
        if not math.isfinite(delta_t_f) or delta_t_f < 0:
            raise ValueError("delta_t_f must be finite and non-negative")
        return float(delta_t_f)
    if sensible_load_btuh is not None:
        try:
            load = float(sensible_load_btuh)
        except (TypeError, ValueError) as exc:
            raise ValueError("sensible_load_btuh must be numeric") from exc
        if not math.isfinite(load) or load < 0:
            raise ValueError("sensible_load_btuh must be finite and non-negative")
        return calculate_supply_delta_t(load, total_cfm)
    return None


def _reject_total_load(total_load_btuh: float | None) -> None:
    """Prevent total cooling load from being used as sensible heat load."""
    if total_load_btuh is not None:
        raise ValueError(
            "total_load_btuh cannot be used for diffuser ΔT; provide "
            "sensible_load_btuh or delta_t_f instead")


def diffuser_face_half_extent_m(selection: object) -> float:
    """Conservative center-to-face extent for wall-clearance checks."""
    size_label = str(getattr(selection, "size_label", ""))
    match = re.search(r"\d+(?:\.\d+)?", size_label)
    if match is None:
        raise ValueError(f"Cannot determine diffuser face size from {size_label!r}")
    half_width_m = ft_to_m(float(match.group()) / 12.0) / 2.0
    if getattr(selection, "kind", "") == "round":
        return half_width_m
    return half_width_m * math.sqrt(2.0)


def selection_input_signature(
        total_cfm: float, sensible_load_btuh: float | None,
        geometry_signature: dict[str, object], type_label: str,
        application: str, max_nc: float | None,
        max_dp_inwg: float,
        selected_option_index: int | None = None) -> dict[str, object]:
    """Stable inputs required to safely reuse a cached diffuser selection."""
    signature = {
        "cfm": float(total_cfm),
        "sensible_load_btuh": (
            float(sensible_load_btuh) if sensible_load_btuh is not None else None),
        "geometry": geometry_signature,
        "type_label": str(type_label),
        "application": str(application),
        "max_nc": float(max_nc) if max_nc is not None else None,
        "max_dp_inwg": float(max_dp_inwg),
    }
    if selected_option_index is not None:
        signature["selected_option_index"] = int(selected_option_index)
    return signature


def selection_signatures_match(saved: object, current: dict[str, object]) -> bool:
    """Only reuse a selection when every recorded input still matches."""
    return isinstance(saved, dict) and saved == current
