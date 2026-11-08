"""Regras de seleção e constantes de projeto dos difusores (movido de diffuser_calculator.py)."""
from __future__ import annotations

import math

from ductdx.difusores import dados_catalogo as _cd

# ─────────────────────────────────────────────────────────────
#  Documented selection rules (data: catalog_data.DIFFUSER_RULES)
# ─────────────────────────────────────────────────────────────
_BTUH_PER_FT2_TO_W_PER_M2 = 0.29307107 * 10.7639104


def _rule(rule_id: str) -> dict:
    return _cd.DIFFUSER_RULES[rule_id]


def rules_application_nc() -> dict[str, float]:
    """NC limit per application; policy 'current' (legacy) or 'ashrae_ch48'."""
    nc = _rule("R-NC")
    key = "limit_ch48" if nc.get("policy") == "ashrae_ch48" else "limit"
    return {k: float(v[key]) for k, v in nc["application"].items()}


def rules_tl_target() -> float:
    """T/L giving maximum ADPI for circular ceiling diffusers (Table 4: 0.8)."""
    return float(_rule("R-TL-BAND")["target_t_over_l"])


def rules_load_w_m2(sensible_btuh: float | None,
                    floor_area_ft2: float) -> float | None:
    if sensible_btuh is None or floor_area_ft2 <= 0 or sensible_btuh <= 0:
        return None
    return sensible_btuh / floor_area_ft2 * _BTUH_PER_FT2_TO_W_PER_M2


def rules_tl_band(load: float | None) -> tuple[float, float]:
    """T50/L band (lo, hi) for a cooling load in W/m2 (R-TL-BAND).

    Between tabulated loads the intersection of the two neighbouring bands is
    used (conservative); outside 60-250 W/m2 or with no load the fallback band.
    """
    r = _rule("R-TL-BAND")
    fb = (r["fallback"]["lo"], r["fallback"]["hi"])
    if load is None:
        return fb
    rows = sorted(r["table"], key=lambda x: x["load_w_m2"])
    if load < rows[0]["load_w_m2"] or load > rows[-1]["load_w_m2"]:
        return fb
    for row in rows:
        if abs(load - row["load_w_m2"]) < 1e-9:
            return row["lo"], row["hi"]
    for a, b in zip(rows, rows[1:], strict=False):
        if a["load_w_m2"] <= load <= b["load_w_m2"]:
            return max(a["lo"], b["lo"]), min(a["hi"], b["hi"])
    return fb


def rules_drop_to_occupied_zone_ft(room_h_ft: float) -> float:
    r = _rule("R-CHAR-L")
    if not r.get("include_drop", False):
        return 0.0
    return max(0.0, room_h_ft - float(r["occupied_zone_top_ft"]))


def rules_min_throw_prefilter_enabled() -> bool:
    return bool(_rule("R-MIN-THROW").get("enabled", False))


# ─────────────────────────────────────────────────────────────
#  Catalog rules (Table 4, p.5)  /  design rules
# ─────────────────────────────────────────────────────────────
# ceiling height (ft) -> (max CFM per diffuser, max supply ΔT °F)
CEILING_TABLE = {8: (800, 20), 10: (2000, 26), 12: (3000, 30),
                 14: (5000, 30), 16: (6400, 30)}
CEILING_MAX_CFM = {h: v[0] for h, v in CEILING_TABLE.items()}   # compat

# T50/L screening bands inspired by ADPI guidance. This geometric proxy is
# not a validated ADPI calculation and does not establish ASHRAE Standard 55
# compliance. Confirm actual room-air performance with manufacturer data or
# a validated analysis.
ADPI_BANDS = {"round": (0.7, 1.2), "square": (0.7, 1.2), "square3": (0.7, 1.2)}

# Rule of thumb (NOT from the catalog): one outlet per at most this floor area.
# Sparse coverage (area/n > MAX) is a warning, not a hard search floor — a
# short T50/L ratio is fixed by *fewer, larger* outlets, which this cap
# must not prevent. MIN is a density ceiling (too many tiny outlets).
MAX_AREA_PER_DIFFUSER_FT2 = 400.0
MIN_AREA_PER_DIFFUSER_FT2 = 60.0      # …and not more than one per this area
IRREGULAR_LAYOUT_SAMPLE_STEP_M = 0.20
IRREGULAR_LAYOUT_RELAXATION_ITERATIONS = 30
IRREGULAR_LAYOUT_MAX_ASSIGNMENTS = 20_000

# Catalog / ASHRAE sensible-heat factor: Q (Btu/h) = 1.08 × CFM × ΔT (°F)
SENSIBLE_HEAT_FACTOR = 1.08
# Neck velocity band that still produces useful throw without excess NC.
PREFERRED_NECK_FPM = (400.0, 800.0)

# Upper NC limit by application (ASHRAE guide, catalog Table 2, p.4)
APPLICATION_NC = rules_application_nc()   # R-NC (catalog_data.DIFFUSER_RULES)
BAND_NC = {0: 20.0, 1: 30.0, 2: 40.0, 3: 45.0}       # catalog colour -> NC upper bound
BAND_LABEL = {0: "≤20", 1: "≤30", 2: "≤40", 3: ">40"}


def calculate_supply_delta_t(load_btuh: float, total_cfm: float) -> float | None:
    """Supply-to-room ΔT (°F) from Q = 1.08 × CFM × ΔT.

    ``load_btuh`` must be the sensible coil load. Total cooling load includes
    latent load and cannot be used to infer dry-bulb ΔT. Returns None when
    inputs are not usable.
    """
    try:
        load = float(load_btuh)
        cfm = float(total_cfm)
    except (TypeError, ValueError):
        return None
    if load <= 0 or cfm <= 0 or not math.isfinite(load) or not math.isfinite(cfm):
        return None
    return load / (SENSIBLE_HEAT_FACTOR * cfm)

