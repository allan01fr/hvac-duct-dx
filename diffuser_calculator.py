"""
diffuser_calculator.py  (v3 – catalog-table driven)
===================================================
Every performance number (CFM, total pressure, throw, NC / noise band) is
interpolated from the AL-ANDALOSIA catalog tables stored in catalog_data.py
(pp. 6, 11, 14).  Nothing is extrapolated silently.

Design screening rules that are NOT in the catalog are isolated in the
constants below and are easy to change:
    ADPI_BANDS, MAX_AREA_PER_DIFFUSER_FT2, APPLICATION_NC.
"""
from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

import catalog_data as _cd
from ductdx.difusores.catalogo_insuflamento import (  # noqa: F401
    ANDALOSIA_SUPPLY_3SCD,
    ANDALOSIA_SUPPLY_4SCD,
    ANDALOSIA_SUPPLY_CCD,
    SUPPLY_CATALOG,
    DiffuserModel,
    Perf,
    _build,
    _interp,
    calculate_performance,
    get_catalog,
    neck_velocity,
    performance,
)
from ductdx.difusores.conversoes import (  # noqa: F401
    ft2_to_m2,
    ft_to_m,
    m2_to_ft2,
    m_to_ft,
)
from ductdx.difusores.entrada import (  # noqa: F401
    _reject_total_load,
    _resolve_delta_t,
    diffuser_face_half_extent_m,
    selection_input_signature,
    selection_signatures_match,
)
from ductdx.difusores.geometria import (  # noqa: F401
    _distance_to_segment,
    _ray_distance_to_polygon,
    distance_to_polygon_walls,
    point_in_polygon,
    polygon_area,
    polygon_bounds,
)
from ductdx.difusores.posicionamento import (  # noqa: F401
    GeometryPlacementResult,
    _legacy_place_diffusers_in_geometry_impl,
    distribute_polygon_positions,
    place_diffusers_in_geometry,
)
from ductdx.difusores.regras import (  # noqa: F401
    _BTUH_PER_FT2_TO_W_PER_M2,
    ADPI_BANDS,
    APPLICATION_NC,
    BAND_LABEL,
    BAND_NC,
    CEILING_MAX_CFM,
    CEILING_TABLE,
    IRREGULAR_LAYOUT_MAX_ASSIGNMENTS,
    IRREGULAR_LAYOUT_RELAXATION_ITERATIONS,
    IRREGULAR_LAYOUT_SAMPLE_STEP_M,
    MAX_AREA_PER_DIFFUSER_FT2,
    MIN_AREA_PER_DIFFUSER_FT2,
    PREFERRED_NECK_FPM,
    SENSIBLE_HEAT_FACTOR,
    _rule,
    calculate_supply_delta_t,
    rules_application_nc,
    rules_drop_to_occupied_zone_ft,
    rules_load_w_m2,
    rules_min_throw_prefilter_enabled,
    rules_tl_band,
    rules_tl_target,
)
from ductdx.difusores.sala import (  # noqa: F401
    _RULE_PREFIXES,
    Grid,
    RoomLayout,
    _band,
    _with_load,
    ach,
    adpi_check,
    best_grid,
    grid_positions,
    jet_collision_warnings,
    room_layout_from_cad,
    room_layout_from_geometry,
    violated_rule_ids,
)
from room_geometry import RoomGeometry

logger = logging.getLogger(__name__)

Kind = Literal["round", "square", "square3"]


# ─────────────────────────────────────────────────────────────
#  Selection
# ─────────────────────────────────────────────────────────────
@dataclass
class DiffuserSelection:
    model: str
    size_label: str
    qty: int
    cfm_per_unit: float
    neck_velocity_fpm: float
    neck_area_ft2: float
    throw_t50_ft: float
    throw_t100_ft: float
    pressure_drop_inwg: float
    nc_estimated: float
    spacing_max_ft: float
    wall_offset_ft: float
    warnings: list[str] = field(default_factory=list)
    # new – single source of truth for GUI / report / CLI
    kind: str = "square"
    nc_label: str = ""
    rows: int = 1
    cols: int = 1
    char_L_ft: float = 0.0
    adpi_ratio: float = 0.0          # worst case  T50 / L_min
    adpi_ratio_min: float = 0.0      # weakest     T50 / L_max
    adpi_ok: bool = True
    score: float = 0.0
    delta_t_f: float | None = None
    delta_t_limit_f: float | None = None
    max_nc_limit: float | None = None
    pressure_ok: bool = True
    max_dp_limit_inwg: float | None = None
    rationale: dict[str, object] = field(default_factory=dict)


def ceiling_limits(height_ft: float) -> tuple[int, float, float, list[str]]:
    """Interpolate Table 4 limits between validated ceiling-height rows."""
    notes = []
    if height_ft > max(CEILING_TABLE):
        notes.append(
            f"Ceiling height {height_ft:.1f} ft exceeds validated Table 4 "
            f"data (maximum {max(CEILING_TABLE)} ft); manufacturer review "
            "is required.")
    heights = sorted(CEILING_TABLE)
    if height_ft < heights[0]:
        h = heights[0]
        notes.append("Ceiling lower than 8 ft – Table 4 row for 8 ft used.")
        return h, *CEILING_TABLE[h], notes

    lower_heights = [height for height in heights if height <= height_ft]
    lower = lower_heights[-1]
    if lower == heights[-1] or height_ft == lower:
        cfm_cap, delta_t_max = CEILING_TABLE[lower]
        return lower, cfm_cap, delta_t_max, notes

    upper = next(height for height in heights if height > height_ft)
    fraction = (height_ft - lower) / (upper - lower)
    lower_cfm, lower_delta_t = CEILING_TABLE[lower]
    upper_cfm, upper_delta_t = CEILING_TABLE[upper]
    cfm_cap = lower_cfm + fraction * (upper_cfm - lower_cfm)
    delta_t_max = lower_delta_t + fraction * (
        upper_delta_t - lower_delta_t)
    return lower, cfm_cap, delta_t_max, notes


@dataclass(frozen=True)
class ReturnDiffuserResult:
    quantity: int
    size_in: int
    cfm_each: float
    velocity_fpm: float
    pressure_drop_inwg: float
    nc: float
    nc_label: str
    warnings: tuple[str, ...] = ()


def return_diffuser_performance(size_in: int, cfm_each: float
                                ) -> ReturnDiffuserResult:
    """Calculate return CCD velocity, pressure, and NC without throw."""
    try:
        row = _cd.RETURN_CCD[size_in]
    except KeyError as exc:
        raise ValueError(f"Unsupported return CCD size: {size_in}") from exc
    if not math.isfinite(cfm_each) or cfm_each <= 0:
        raise ValueError("Return diffuser airflow must be finite and positive")
    velocity = cfm_each / row["area"]
    if not _cd.RETURN_VELOCITY_FPM[0] <= velocity <= _cd.RETURN_VELOCITY_FPM[-1]:
        raise ValueError("Return diffuser velocity is outside catalogue range")
    pressure = _interp(velocity, _cd.RETURN_VELOCITY_FPM, row["pt"])
    nc = _interp(velocity, _cd.RETURN_VELOCITY_FPM, row["nc"])
    nc_label = "<20" if nc < 20 else f"{nc:.0f}"
    return ReturnDiffuserResult(
        quantity=1,
        size_in=size_in,
        cfm_each=cfm_each,
        velocity_fpm=velocity,
        pressure_drop_inwg=pressure,
        nc=nc,
        nc_label=nc_label,
    )


def select_return_diffusers(
        total_return_cfm: float, application: str = "office_priv",
        max_nc: float | None = None, max_dp: float = 0.20,
        ceiling_height_ft: float = 10.0) -> ReturnDiffuserResult:
    """Choose the fewest return CCDs meeting neck velocity, NC, and pressure limits."""
    if not math.isfinite(total_return_cfm) or total_return_cfm <= 0:
        raise ValueError("Total return airflow must be finite and positive")
    if not math.isfinite(max_dp) or max_dp < 0:
        raise ValueError("Maximum return diffuser pressure must be finite and non-negative")
    nc_limit = (
        APPLICATION_NC.get(application, 35) if max_nc is None else max_nc)
    if not math.isfinite(nc_limit) or nc_limit < 0:
        raise ValueError("Maximum return diffuser NC must be finite and non-negative")
    _, table4_cap, _, _ = ceiling_limits(ceiling_height_ft)
    maximum_each = _cd.RETURN_VELOCITY_FPM[-1] * max(
        row["area"] for row in _cd.RETURN_CCD.values())
    minimum_quantity = max(1, math.ceil(total_return_cfm / maximum_each))
    minimum_each = _cd.RETURN_VELOCITY_FPM[0] * min(
        row["area"] for row in _cd.RETURN_CCD.values())
    max_quantity = max(minimum_quantity, int(total_return_cfm / minimum_each))
    candidates = []
    for quantity in range(minimum_quantity, max_quantity + 1):
        cfm_each = total_return_cfm / quantity
        for size_in, row in _cd.RETURN_CCD.items():
            velocity = cfm_each / row["area"]
            if not (_cd.RETURN_VELOCITY_FPM[0] <= velocity
                    <= _cd.RETURN_VELOCITY_FPM[-1]):
                continue
            pressure = _interp(velocity, _cd.RETURN_VELOCITY_FPM, row["pt"])
            nc = _interp(velocity, _cd.RETURN_VELOCITY_FPM, row["nc"])
            if nc <= nc_limit and pressure <= max_dp:
                candidates.append((
                    quantity, pressure, nc, row["area"], size_in,
                    cfm_each, velocity))
    if not candidates:
        raise ValueError(
            "No return CCD selection meets NC, pressure, and catalogue velocity limits")
    quantity, pressure, nc, _, size_in, cfm_each, velocity = min(candidates)
    warnings = ()
    if cfm_each > table4_cap:
        warnings = (
            (f"Return airflow {cfm_each:.0f} CFM per diffuser exceeds the "
             f"Table 4 supply-only reference of {table4_cap} CFM; review required."),
        )
    return ReturnDiffuserResult(
        quantity=quantity,
        size_in=size_in,
        cfm_each=cfm_each,
        velocity_fpm=velocity,
        pressure_drop_inwg=pressure,
        nc=nc,
        nc_label="<20" if nc < 20 else f"{nc:.0f}",
        warnings=warnings,
    )


@dataclass(frozen=True)
class VCDSelection:
    nominal_width_mm: int | None
    nominal_height_mm: int | None
    casing_width_mm: float
    casing_height_mm: float
    face_width_mm: float
    face_height_mm: float
    damper_count: int
    per_damper_width_mm: float
    blade_count: int | None
    drive_arm_x_mm: int | None
    custom_size: bool
    warnings: tuple[str, ...]


def _round_vcd_dimension_up(dimension_mm: float) -> int | None:
    return next(
        (standard for standard in _cd.VCD_STANDARD_L_MM
         if standard >= dimension_mm),
        None,
    )


def vcd_select(duct_w_mm: float, duct_h_mm: float) -> VCDSelection:
    """Select VCD modules, rounding standard sizes up independently per axis."""
    if (not math.isfinite(duct_w_mm) or duct_w_mm <= 0
            or not math.isfinite(duct_h_mm) or duct_h_mm <= 0):
        raise ValueError("VCD duct dimensions must be finite and positive")
    width_nominal = _round_vcd_dimension_up(duct_w_mm)
    height_nominal = _round_vcd_dimension_up(duct_h_mm)
    if width_nominal is not None:
        face_width = float(width_nominal + 4)
        per_damper_width = float(width_nominal)
        damper_count = 1
    elif duct_w_mm > 2000:
        per_damper_width = (duct_w_mm - 60) / 2
        face_width = duct_w_mm
        damper_count = 2
    else:
        per_damper_width = duct_w_mm
        face_width = duct_w_mm + 4
        damper_count = 1
    if height_nominal is not None:
        face_height = float(height_nominal + 4)
    else:
        face_height = duct_h_mm + 4
    custom = width_nominal is None or height_nominal is None
    warnings = (
        ("custom size - confirm with manufacturer",) if custom else ())
    drive_arm_x = (
        _cd.VCD_DRIVE_ARM_X_MM.get(height_nominal)
        if height_nominal is not None else None)
    blade_count = (
        height_nominal // _cd.VCD_BLADE_PITCH_MM
        if height_nominal is not None else None)
    return VCDSelection(
        nominal_width_mm=width_nominal,
        nominal_height_mm=height_nominal,
        casing_width_mm=face_width,
        casing_height_mm=face_height,
        face_width_mm=face_width,
        face_height_mm=face_height,
        damper_count=damper_count,
        per_damper_width_mm=per_damper_width,
        blade_count=blade_count,
        drive_arm_x_mm=drive_arm_x,
        custom_size=custom,
        warnings=warnings,
    )


def vcd_face_velocity_fpm(cfm: float, duct_w_mm: float,
                          duct_h_mm: float) -> float:
    """Calculate VCD face velocity from airflow and selected casing area."""
    if not math.isfinite(cfm) or cfm < 0:
        raise ValueError("VCD airflow must be finite and non-negative")
    selection = vcd_select(duct_w_mm, duct_h_mm)
    area_ft2 = (
        selection.face_width_mm * selection.face_height_mm
        / (304.8 ** 2))
    return cfm / area_ft2


def vcd_pressure_drop(velocity_fpm: float) -> float:
    """Estimated opposed-blade VCD ΔP from the supplied log-log graph."""
    if not math.isfinite(velocity_fpm) or velocity_fpm < 0:
        raise ValueError("VCD face velocity must be finite and non-negative")
    return _cd.VCD_DP_COEFFICIENT * velocity_fpm ** 2


def vcd_pressure_drop_for_duct(cfm: float, duct_w_mm: float,
                               duct_h_mm: float) -> float:
    return vcd_pressure_drop(
        vcd_face_velocity_fpm(cfm, duct_w_mm, duct_h_mm))


def vcd_closed_leakage_cfm(area_ft2: float,
                           pressure_inwg: float) -> float:
    """Estimated closed leakage interpolated from supplied pressure points."""
    if not math.isfinite(area_ft2) or area_ft2 < 0:
        raise ValueError("VCD face area must be finite and non-negative")
    pressures = tuple(_cd.VCD_CLOSED_LEAKAGE_CFM_PER_FT2)
    if not math.isfinite(pressure_inwg) or not pressures[0] <= pressure_inwg <= pressures[-1]:
        raise ValueError("VCD leakage estimate is available from 0.5 to 4 in.wg")
    leakage_per_ft2 = _interp(
        pressure_inwg, pressures,
        tuple(_cd.VCD_CLOSED_LEAKAGE_CFM_PER_FT2[p] for p in pressures))
    return leakage_per_ft2 * area_ft2


@dataclass(frozen=True)
class RVCDSelection:
    pressure_class: str
    diameter_in: float
    frame_allowance_in: float | None
    overall_length_in: float | None
    velocity_fpm: float
    pressure_drop_inwg: float
    leakage_cfm_at_1_inwg: float
    pressure_drop_estimated: bool
    leakage_estimated: bool
    warning: str | None = None


def rvcd_select(diameter_in: float, cfm: float,
                pressure_class: str = "LP") -> RVCDSelection:
    """Calculate RVCD dimensions and estimated loss using the 8-inch anchor."""
    if not math.isfinite(diameter_in) or diameter_in <= 0:
        raise ValueError("RVCD diameter must be finite and positive")
    if not math.isfinite(cfm) or cfm < 0:
        raise ValueError("RVCD airflow must be finite and non-negative")
    pressure_class = pressure_class.upper()
    if pressure_class not in {"LP", "HP"}:
        raise ValueError("RVCD pressure class must be LP or HP")
    frame_allowance = next(
        allowance for upper_bound, allowance in _cd.RVCD_FRAME_ALLOWANCE_IN
        if diameter_in <= upper_bound
    )
    warning = None
    if frame_allowance is None:
        warning = (
            'RVCD frame allowance for diameters 0–9-7/8" is a PDF typo; '
            "dimension must be confirmed with the manufacturer.")
    area_ft2 = math.pi * (diameter_in / 12) ** 2 / 4
    velocity = cfm / area_ft2
    pressure_drop = _cd.RVCD_DP_COEFFICIENT * (
        velocity / _cd.RVCD_REFERENCE_VELOCITY_FPM) ** 2
    leakage = (
        _cd.RVCD_LEAKAGE_CFM_PER_PERIMETER_IN_AT_1_INWG
        * math.pi * diameter_in)
    return RVCDSelection(
        pressure_class=pressure_class,
        diameter_in=diameter_in,
        frame_allowance_in=frame_allowance,
        overall_length_in=(
            diameter_in + frame_allowance
            if frame_allowance is not None else None),
        velocity_fpm=velocity,
        pressure_drop_inwg=pressure_drop,
        leakage_cfm_at_1_inwg=leakage,
        pressure_drop_estimated=True,
        leakage_estimated=True,
        warning=warning,
    )


@dataclass(frozen=True)
class AccessDoorSelection:
    width_in: int
    height_in: int
    min_cfm: int
    max_cfm: int
    area_in2: int
    range_midpoint_cfm: float
    notes: tuple[str, ...] = ()

    @property
    def size_label(self) -> str:
        return f"{self.width_in}×{self.height_in}"


def access_door_select(cfm: float) -> AccessDoorSelection:
    """Select the smallest compatible access-door face area, then nearest range midpoint."""
    if not math.isfinite(cfm) or cfm <= 0:
        raise ValueError("Access-door airflow must be finite and positive")
    candidates = []
    for (width, height), (minimum, maximum) in _cd.ACCESS_DOORS.items():
        if minimum <= cfm <= maximum:
            midpoint = (minimum + maximum) / 2
            candidates.append((
                width * height, abs(cfm - midpoint), width, height,
                minimum, maximum, midpoint))
    if not candidates:
        raise ValueError(
            f"No access-door size is catalogued for {cfm:.0f} CFM")
    area, _, width, height, minimum, maximum, midpoint = min(candidates)
    notes = (
        *_cd.ACCESS_DOOR_CATALOG_WARNINGS,
        *_cd.ACCESS_DOOR_CATALOG_NOTES.get((width, height), ()),
    )
    return AccessDoorSelection(
        width, height, minimum, maximum, area, midpoint, tuple(notes))


def _geometry_min_qty(room: RoomLayout | None) -> int:
    """At least one diffuser per significant L-shape / orthogonal wing."""
    if room is None or room.geometry is None:
        return 1
    try:
        from placement_engine import significant_subrectangle_count
        return max(1, significant_subrectangle_count(room.geometry.vertices))
    except ImportError:
        return 1


def _hard_warning_count(warnings: Sequence[str]) -> int:
    hard_prefixes = (
        "Neck velocity", "ΔP ", "Noise NC", "Supply ΔT",
    )
    hard_needles = ("exceeds Table 4",)
    n = 0
    for warning in warnings:
        if any(warning.startswith(p) for p in hard_prefixes) or any(
                needle in warning for needle in hard_needles):
            n += 1
    return n


def _neck_velocity_penalty(v_fpm: float) -> float:
    """Keep throw-capable neck velocity; do not reward NC 20 from a dead jet."""
    lo, hi = PREFERRED_NECK_FPM
    if v_fpm < lo:
        return 0.18 * (lo - v_fpm)
    if v_fpm > hi:
        return 0.08 * (v_fpm - hi)
    return 0.0


def _evaluate(d: DiffuserModel, n: int, total_cfm: float, room: RoomLayout | None,
              max_nc: float, max_dp: float, cfm_cap: float,
              min_qty: int, delta_t_f: float | None = None,
              include_tl_screening: bool = True
              ) -> DiffuserSelection:
    q = total_cfm / n
    p = performance(d, q)
    viol: list[str] = []
    if not p.in_range:
        viol.append(f"Neck velocity {p.v_fpm:.0f} FPM outside catalog table "
                    f"({d.v[0]:.0f}-{d.v[-1]:.0f})")
    if p.pt > max_dp:
        viol.append(f"ΔP {p.pt:.3f} > limit {max_dp:.2f} in.wg")
    if p.nc > max_nc:
        viol.append(f"Noise NC {p.nc_label} above limit {max_nc:.0f}")
    if q > cfm_cap:
        viol.append(f"{q:.0f} CFM/diffuser exceeds Table 4 limit ({cfm_cap:.0f})")
    if n < min_qty:
        viol.append(f"Only {n} diffuser(s): Table 4 / geometry need ≥{min_qty}")
    if room is not None and room.floor_area_ft2 / n < MIN_AREA_PER_DIFFUSER_FT2:
        viol.append(f"{n} diffusers is too dense (<{MIN_AREA_PER_DIFFUSER_FT2:.0f} ft² each)")
    if room is not None and room.floor_area_ft2 / n > MAX_AREA_PER_DIFFUSER_FT2:
        viol.append(
            f"{n} diffuser(s) cover {room.floor_area_ft2 / n:.0f} ft² each "
            f"(>{MAX_AREA_PER_DIFFUSER_FT2:.0f} ft² rule of thumb)")

    rows = cols = 1
    L = r_hi = r_lo = 0.0
    aspect = 1.0
    ok = True
    spacing = wall = 0.0
    if room is not None:
        g = best_grid(room, n)
        rows, cols, aspect, L = g.rows, g.cols, g.aspect, g.L_min
        lo, hi = _band(d.kind, room)
        r_hi, r_lo, ok, _ = _t50_l_ratios(
            p.t50, p.t50_back, (lo, hi), grid=g)
        if not ok and include_tl_screening:
            viol.append(
                f"T50/L screening {r_lo:.2f}–{r_hi:.2f} outside band {lo}-{hi}")
        spacing = round(2 * p.t50 / lo, 1)
        wall = round(g.L_min, 1)
    adpi_c = (r_hi + r_lo) / 2.0 if room is not None else rules_tl_target()
    lo_b, hi_b = _band(d.kind, room)
    if ok and lo_b <= adpi_c <= hi_b:
        adpi_penalty = 25.0 * abs(adpi_c - rules_tl_target())
    else:
        undershoot = max(0.0, lo_b - r_lo)
        overshoot = max(0.0, r_hi - hi_b)
        adpi_penalty = 800.0 + 250.0 * (undershoot + overshoot)
    # NC compliance is a hard ranking criterion; score only breaks ties.
    score = (
        adpi_penalty
        + 45.0 * n
        + 0.25 * p.nc
        + _neck_velocity_penalty(p.v_fpm)
        + 40.0 * p.pt
        + 6.0 * (aspect - 1.0)
        - 4.0 * d.neck_dia_inch
    )
    return DiffuserSelection(
        model=d.model, size_label=d.size_label, qty=n, cfm_per_unit=round(q, 1),
        neck_velocity_fpm=round(p.v_fpm, 1), neck_area_ft2=d.neck_area_ft2,
        throw_t50_ft=round(p.t50, 1), throw_t100_ft=round(p.t100, 1),
        pressure_drop_inwg=round(p.pt, 4), nc_estimated=round(p.nc, 1),
        spacing_max_ft=spacing, wall_offset_ft=wall, warnings=viol, kind=d.kind,
        nc_label=p.nc_label, rows=rows, cols=cols, char_L_ft=round(L, 2),
        adpi_ratio=round(r_hi, 2), adpi_ratio_min=round(r_lo, 2), adpi_ok=ok,
        score=round(score, 2), delta_t_f=delta_t_f,
        delta_t_limit_f=ceiling_limits(room.room_h_ft)[2]
        if room is not None else None, max_nc_limit=max_nc,
        pressure_ok=p.pt <= max_dp + 1e-9,
        max_dp_limit_inwg=max_dp)


def _t50_l_ratios(
        t50: float, t50_back: float,
        band: tuple[float, float],
        positions: Sequence[tuple[float, float]] | None = None,
        polygon: Sequence[tuple[float, float]] | None = None,
        drop_ft: float = 0.0,
        grid=None) -> tuple[float, float, bool, float]:
    """Estimate geometric T50/L screening, not actual ADPI."""
    lo, hi = band
    if grid is not None:
        r_hi = t50 / grid.L_min
        r_lo = t50_back / grid.L_max
        return r_hi, r_lo, r_hi <= hi and r_lo >= lo, grid.L_min
    if positions is None or polygon is None or len(polygon) < 3:
        raise ValueError("Polygon T50/L screening requires room boundary points")
    directions = ((1, 0), (-1, 0), (0, 1), (0, -1))
    hi_lengths = []
    lo_lengths = []
    for i, (x, y) in enumerate(positions):
        directional_lengths = []
        for dx_dir, dy_dir in directions:
            wall_d = _ray_distance_to_polygon(x, y, dx_dir, dy_dir, polygon)
            neighbour_halves = []
            for j, (ox, oy) in enumerate(positions):
                if i == j:
                    continue
                dx, dy = ox - x, oy - y
                in_cone = (
                    (dx_dir > 0 and dx > 0 and abs(dy) <= abs(dx))
                    or (dx_dir < 0 and dx < 0 and abs(dy) <= abs(dx))
                    or (dy_dir > 0 and dy > 0 and abs(dx) <= abs(dy))
                    or (dy_dir < 0 and dy < 0 and abs(dx) <= abs(dy))
                )
                if in_cone:
                    # R-CHAR-L: mixed jets -> half spacing + drop to occupied zone
                    neighbour_halves.append(math.hypot(dx, dy) / 2.0 + drop_ft)
            nb_d = min(neighbour_halves, default=float("inf"))
            directional_lengths.append(min(wall_d, nb_d))
        hi_lengths.append(min(directional_lengths))
        lo_lengths.append(max(directional_lengths))

    r_hi = max((t50 / max(length, 0.1) for length in hi_lengths), default=0.0)
    r_lo = min((t50_back / max(length, 0.1) for length in lo_lengths), default=0.0)
    ok = r_hi <= hi and r_lo >= lo
    characteristic = min(hi_lengths, default=0.0)
    return r_hi, r_lo, ok, characteristic


_ARG_UNSET = object()


def evaluate_layout(total_cfm: float,
                    *args,
                    positions_ft: Sequence[tuple[float, float]] | None | object = _ARG_UNSET,
                    room: RoomLayout | None | object = _ARG_UNSET,
                    application: str | object = _ARG_UNSET,
                    catalog: list[DiffuserModel] | object = _ARG_UNSET,
                    max_nc: float | None | object = _ARG_UNSET,
                    max_dp_inwg: float | object = _ARG_UNSET,
                    delta_t_f: float | None | object = _ARG_UNSET,
                    top: int | object = _ARG_UNSET,
                    total_load_btuh: float | None | object = _ARG_UNSET,
                    sensible_load_btuh: float | None | object = _ARG_UNSET
                    ) -> tuple[DiffuserSelection, list[DiffuserSelection]]:
    """Evaluate a fixed layout using ``(total_cfm, positions_ft, room, ...)``.

    Also accepts the older ``(total_cfm, application, catalog, ...)`` order
    when ``positions_ft`` and ``room`` are supplied by keyword.
    """
    values = {
        "positions_ft": positions_ft,
        "room": room,
        "application": application,
        "catalog": catalog,
        "max_nc": max_nc,
        "max_dp_inwg": max_dp_inwg,
        "delta_t_f": delta_t_f,
        "top": top,
        "total_load_btuh": total_load_btuh,
        "sensible_load_btuh": sensible_load_btuh,
    }
    if args and isinstance(args[0], str):
        if len(args) > 2:
            raise TypeError("Legacy evaluate_layout calls accept application and catalog positionally")
        legacy_names = ("application", "catalog")
        for name, value in zip(legacy_names, args, strict=False):
            if values[name] is not _ARG_UNSET:
                raise TypeError(
                    f"evaluate_layout got multiple values for {name}")
            values[name] = value
    elif args:
        positional_names = (
            "positions_ft", "room", "application", "catalog", "max_nc",
            "max_dp_inwg", "delta_t_f", "top", "total_load_btuh",
            "sensible_load_btuh",
        )
        if len(args) > len(positional_names):
            raise TypeError("evaluate_layout received too many positional arguments")
        for name, value in zip(positional_names, args, strict=False):
            if values[name] is not _ARG_UNSET:
                raise TypeError(
                    f"evaluate_layout got multiple values for {name}")
            values[name] = value
    defaults = {
        "positions_ft": None,
        "room": None,
        "application": "office_priv",
        "catalog": ANDALOSIA_SUPPLY_CCD,
        "max_nc": None,
        "max_dp_inwg": 0.20,
        "delta_t_f": None,
        "top": 5,
        "total_load_btuh": None,
        "sensible_load_btuh": None,
    }
    values = {
        name: default if value is _ARG_UNSET else value
        for name, default in defaults.items()
        for value in (values[name],)
    }
    positions_ft = values["positions_ft"]
    room = values["room"]
    application = values["application"]
    catalog = values["catalog"]
    max_nc = values["max_nc"]
    max_dp_inwg = values["max_dp_inwg"]
    delta_t_f = values["delta_t_f"]
    top = values["top"]
    total_load_btuh = values["total_load_btuh"]
    sensible_load_btuh = values["sensible_load_btuh"]
    if positions_ft is None:
        raise TypeError("evaluate_layout requires positions_ft")
    if room is None:
        raise TypeError("evaluate_layout requires room")
    if not math.isfinite(total_cfm) or total_cfm <= 0:
        raise ValueError("total_cfm must be finite and > 0")
    _reject_total_load(total_load_btuh)
    sensible_load = sensible_load_btuh
    delta_t_f = _resolve_delta_t(total_cfm, delta_t_f, sensible_load)
    room = _with_load(room, sensible_load)
    if not positions_ft:
        raise ValueError("At least one diffuser position is required")
    if room.polygon_ft:
        if room.geometry is not None:
            outside = [
                index + 1 for index, point in enumerate(positions_ft)
                if not room.geometry.contains_point(ft_to_m(point[0]),
                                                    ft_to_m(point[1]))
            ]
        else:
            outside = [
                index + 1 for index, point in enumerate(positions_ft)
                if not point_in_polygon(point[0], point[1], room.polygon_ft)
            ]
        if outside:
            raise ValueError(
                "Diffuser positions outside room polygon: "
                + ", ".join(map(str, outside)))
    if max_nc is None or max_nc <= 0:
        max_nc = APPLICATION_NC.get(application, 35)

    height_row, cfm_cap, dt_max, notes = ceiling_limits(room.room_h_ft)
    min_qty = max(
        1,
        math.ceil(total_cfm / cfm_cap),
        math.ceil(room.floor_area_ft2 / MAX_AREA_PER_DIFFUSER_FT2),
        _geometry_min_qty(room),
    )
    extra = list(notes)
    delta_t_warning = (
        f"Supply ΔT {delta_t_f:.0f}°F exceeds Table 4 limit "
        f"{dt_max}°F for the {height_row} ft row."
        if delta_t_f is not None and delta_t_f > dt_max else None)

    candidates = []
    polygon = room.polygon_ft or [
        (0.0, 0.0), (room.room_w_ft, 0.0),
        (room.room_w_ft, room.room_l_ft), (0.0, room.room_l_ft),
    ]
    for model in catalog:
        sel = _evaluate(
            model, len(positions_ft), total_cfm, room, max_nc,
            max_dp_inwg, cfm_cap, min_qty, delta_t_f,
            include_tl_screening=False)
        p = performance(model, total_cfm / len(positions_ft))
        band = _band(model.kind, room)
        r_hi, r_lo, adpi_ok, char_l = _t50_l_ratios(
            p.t50, p.t50_back, band, positions_ft, polygon,
            rules_drop_to_occupied_zone_ft(room.room_h_ft))
        sel.adpi_ratio = round(r_hi, 2)
        sel.adpi_ratio_min = round(r_lo, 2)
        sel.adpi_ok = adpi_ok
        sel.char_L_ft = round(char_l, 2)
        sel.spacing_max_ft = round(2 * p.t50 / band[0], 1)
        sel.wall_offset_ft = round(char_l, 1)
        if not adpi_ok:
            lo, hi = band
            sel.warnings.append(
                f"T50/L screening {r_lo:.2f}–{r_hi:.2f} outside band {lo}-{hi}")
        sel.warnings.extend(
            jet_collision_warnings(
                positions_ft, [p.t50] * len(positions_ft)))
        sel.warnings.extend(extra)
        sel.delta_t_f = delta_t_f
        sel.delta_t_limit_f = float(dt_max)
        geometry = room.geometry
        is_rectangular_polygon = False
        if geometry is not None and len(geometry.vertices) == 4:
            min_x, max_x, min_y, max_y = geometry.bounding_box
            corners = {
                (min_x, min_y), (max_x, min_y),
                (max_x, max_y), (min_x, max_y),
            }
            is_rectangular_polygon = all(
                any(math.dist(point, corner) <= 1e-8 for corner in corners)
                for point in geometry.vertices)
        aspect = (
            max(room.room_w_ft, room.room_l_ft) / max(
                min(room.room_w_ft, room.room_l_ft), 0.1)
            if geometry is None or is_rectangular_polygon else 1.0)
        adpi_c = (r_hi + r_lo) / 2.0
        lo_b, hi_b = band
        if adpi_ok and lo_b <= adpi_c <= hi_b:
            adpi_penalty = 25.0 * abs(adpi_c - rules_tl_target())
        else:
            undershoot = max(0.0, lo_b - r_lo)
            overshoot = max(0.0, r_hi - hi_b)
            adpi_penalty = 800.0 + 250.0 * (undershoot + overshoot)
        sel.score = round(
            adpi_penalty
            + 45.0 * sel.qty
            + 0.25 * p.nc
            + _neck_velocity_penalty(p.v_fpm)
            + 40.0 * p.pt
            + 6.0 * (aspect - 1.0)
            - 4.0 * model.neck_dia_inch,
            2)
        sel.delta_t_f = delta_t_f
        sel.delta_t_limit_f = dt_max
        sel.max_nc_limit = float(max_nc)
        sel.rationale = _selection_rationale(sel)
        sel.rationale.update(tl_band=band, violated_rules=violated_rule_ids(sel.warnings))
        candidates.append(sel)

    candidates.sort(key=_selection_rank_key)
    if not candidates:
        raise RuntimeError("No catalog diffuser can handle this airflow.")
    selected = candidates[:max(0, top)]
    if delta_t_warning:
        # A room-level warning must not influence ranking among models.
        for candidate in selected:
            candidate.warnings.append(delta_t_warning)
            candidate.rationale["violated_rules"] = violated_rule_ids(
                candidate.warnings)
    return selected[0] if selected else candidates[0], selected


def _selection_rank_key(sel: DiffuserSelection) -> tuple:
    """Prefer catalog-valid, throw-screened options before acoustic ties."""
    catalog_warning = any(
        warning.startswith("Neck velocity ") for warning in sel.warnings)
    table4_airflow_warning = any(
        "CFM/diffuser exceeds Table 4" in warning for warning in sel.warnings)
    acoustic_warning = any(
        warning.startswith("Noise NC ") for warning in sel.warnings)
    return (
        catalog_warning,
        table4_airflow_warning,
        0 if sel.adpi_ok else 1,
        acoustic_warning,
        sel.qty,
        -sel.neck_area_ft2,
        _hard_warning_count(sel.warnings),
        sel.score,
    )


def _selection_rationale(sel: DiffuserSelection) -> dict[str, object]:
    """Structured explanation of the criteria met by a ranked candidate."""
    noise_ok = not any(
        warning.startswith("Noise NC ") for warning in sel.warnings)
    table4_ok = not any(
        "CFM/diffuser exceeds Table 4" in warning for warning in sel.warnings)
    pressure_ok = sel.pressure_ok
    jet_collision_flagged = any(
        warning.startswith("Potential jet interaction")
        for warning in sel.warnings)
    rule_statuses = {
        rule_id: str(rule.get("status", "unclassified"))
        for rule_id, rule in _cd.DIFFUSER_RULES.items()
    }
    unresolved_rules = tuple(
        rule_id for rule_id, status in rule_statuses.items()
        if status in {"unresolved", "pending_verification", "not_implemented"}
    )
    engineering_decisions = tuple(
        rule_id for rule_id, status in rule_statuses.items()
        if status == "engineer_decision"
    )
    return {
        "catalog_valid": not any(
            warning.startswith("Neck velocity ") for warning in sel.warnings),
        "noise_compliant": noise_ok,
        "acoustic_verification_status": (
            "Acoustic screening; catalog NC basis unresolved"
            if rule_statuses.get("R-NC-BASIS") == "unresolved"
            else "Acoustic screening"),
        "pressure_ok": pressure_ok,
        "pressure_basis": "catalog total-pressure loss; system losses not included",
        "jet_collision_screening": (
            "Potential overlap flagged; direction and occupied-zone velocity not verified"
            if jet_collision_flagged
            else "No geometric T50-envelope overlap flagged; collision not verified"),
        "t50_l_screening_pass": sel.adpi_ok,
        "table4_airflow_compliant": table4_ok,
        "verification_status": "ASHRAE-aligned screening; ADPI not verified",
        "t50_l_basis": "T0.25/L cooling screening; catalog T50 used as ~50 fpm proxy",
        "terminal_velocity_status": rule_statuses.get(
            "R-TERMINAL-VELOCITY", "unclassified"),
        "rule_statuses": rule_statuses,
        "unresolved_or_unimplemented_rules": unresolved_rules,
        "engineering_decision_rules": engineering_decisions,
        "adpi_verified": False,
        "source_refs": [
            "ASHRAE HVAC Applications 2015 Ch.57 pp.57.5-57.6",
            "ASHRAE HVAC Applications 2015 Ch.48 p.48.3",
            "ASHRAE Fundamentals 2017 Ch.20",
        ],
        "quantity": sel.qty,
        "summary": (
            f"Selected {sel.qty} × {sel.size_label} for "
            f"T50/L screening {'pass' if sel.adpi_ok else 'review'}; "
            f"NC {'meets' if noise_ok else 'exceeds'} the configured limit; "
            f"catalog total pressure {'meets' if pressure_ok else 'exceeds'} "
            "the configured limit."
        ),
    }


def _projection_axis(points: list[tuple[float, float]]) -> tuple[float, float]:
    mean_x = sum(point[0] for point in points) / len(points)
    mean_y = sum(point[1] for point in points) / len(points)
    xx = sum((x - mean_x) ** 2 for x, _ in points)
    xy = sum((x - mean_x) * (y - mean_y) for x, y in points)
    yy = sum((y - mean_y) ** 2 for _, y in points)
    eigenvalue = (
        xx + yy + math.sqrt((xx - yy) ** 2 + 4.0 * xy ** 2)
    ) / 2.0
    axis = (xy, eigenvalue - xx)
    if math.hypot(*axis) <= 1e-12:
        axis = (1.0, 0.0) if xx >= yy else (0.0, 1.0)
    length = math.hypot(*axis)
    axis = (axis[0] / length, axis[1] / length)
    if axis[0] < 0 or (abs(axis[0]) < 1e-12 and axis[1] < 0):
        axis = (-axis[0], -axis[1])
    return axis


def _alternative_irregular_layouts(
        geometry: RoomGeometry, quantity: int, wall_clearance_m: float,
        min_spacing_m: float,
        existing: list[tuple[float, float]]) -> list[list[tuple[float, float]]]:
    """Generate deterministic, strictly verified layouts for irregular rooms."""
    import placement_engine

    vertices = geometry.vertices
    min_x, max_x, min_y, max_y = geometry.bounding_box
    step = IRREGULAR_LAYOUT_SAMPLE_STEP_M
    samples = []
    y = min_y + step / 2.0
    while y <= max_y - step / 2.0 + 1e-9:
        x = min_x + step / 2.0
        while x <= max_x - step / 2.0 + 1e-9:
            point = (round(x, 6), round(y, 6))
            if (placement_engine.point_in_polygon(point, vertices)
                    and placement_engine.distance_to_boundary(point, vertices)
                    >= wall_clearance_m - 1e-6):
                samples.append(point)
            x += step
        y += step
    samples = sorted(set(samples))
    if len(samples) < quantity:
        return []

    axis = _projection_axis(samples)
    projection = [
        x * axis[0] + y * axis[1] for x, y in samples
    ]

    def snap_to_cells(
            centers: list[tuple[float, float]],
            labels: list[int]) -> list[tuple[float, float]] | None:
        per_cell = []
        for index, center in enumerate(centers):
            members = [
                point for point, label in zip(samples, labels, strict=True)
                if label == index
            ]
            if not members:
                return None
            members.sort(key=lambda point: (
                (point[0] - center[0]) ** 2 + (point[1] - center[1]) ** 2,
                point,
            ))
            per_cell.append(members[:32])

        cell_order = sorted(
            range(len(centers)),
            key=lambda i: (centers[i][0], centers[i][1], i),
        )
        chosen: list[tuple[float, float]] = []
        assignments = 0

        def assign(position: int) -> list[tuple[float, float]] | None:
            nonlocal assignments
            if position == len(cell_order):
                return chosen.copy()
            for point in per_cell[cell_order[position]]:
                assignments += 1
                if assignments > IRREGULAR_LAYOUT_MAX_ASSIGNMENTS:
                    return None
                if all(math.dist(point, prior) >= min_spacing_m - 1e-6
                       for prior in chosen):
                    chosen.append(point)
                    result = assign(position + 1)
                    if result is not None:
                        return result
                    chosen.pop()
            return None

        return assign(0)

    seeds: list[list[tuple[float, float]]] = []
    if len(existing) == quantity:
        seeds.append(list(existing))
    ordered = sorted(range(len(samples)), key=lambda i: (projection[i], i))
    seeds.append([
        samples[ordered[min(
            len(ordered) - 1,
            int((index + 0.5) * len(ordered) / quantity),
        )]]
        for index in range(quantity)
    ])
    center = (
        sum(point[0] for point in samples) / len(samples),
        sum(point[1] for point in samples) / len(samples),
    )
    first = max(
        range(len(samples)),
        key=lambda i: (
            (samples[i][0] - center[0]) ** 2
            + (samples[i][1] - center[1]) ** 2,
            -i,
        ),
    )
    farthest = [samples[first]]
    while len(farthest) < quantity:
        next_index = max(
            range(len(samples)),
            key=lambda i: (
                min(math.dist(samples[i], point) ** 2 for point in farthest),
                -i,
            ),
        )
        farthest.append(samples[next_index])
    seeds.append(farthest)

    layouts: list[list[tuple[float, float]]] = []
    seen: set[tuple[tuple[float, float], ...]] = set()

    def add_verified(points: list[tuple[float, float]] | None) -> None:
        if points is None:
            return
        layout = tuple(sorted(
            (round(point[0], 6), round(point[1], 6)) for point in points
        ))
        if layout in seen:
            return
        seen.add(layout)
        if placement_engine.verify_placement(
                vertices, layout, wall_clearance_m, min_spacing_m).valid:
            layouts.append(list(layout))

    balanced_labels = [0] * len(samples)
    balanced_centers = []
    for index in range(quantity):
        base_size, remainder = divmod(len(samples), quantity)
        start = index * base_size + min(index, remainder)
        end = start + base_size + int(index < remainder)
        indices = ordered[start:end]
        for sample_index in indices:
            balanced_labels[sample_index] = index
        balanced_centers.append((
            sum(samples[i][0] for i in indices) / len(indices),
            sum(samples[i][1] for i in indices) / len(indices),
        ))
    add_verified(snap_to_cells(balanced_centers, balanced_labels))

    for initial in seeds:
        centers = initial.copy()
        for _ in range(IRREGULAR_LAYOUT_RELAXATION_ITERATIONS):
            labels = [
                min(
                    range(quantity),
                    key=lambda i: (
                        (point[0] - centers[i][0]) ** 2
                        + (point[1] - centers[i][1]) ** 2,
                        i,
                    ),
                )
                for point in samples
            ]
            updated = []
            for index, center_point in enumerate(centers):
                members = [
                    point for point, label in zip(samples, labels, strict=True)
                    if label == index
                ]
                updated.append(
                    (sum(point[0] for point in members) / len(members),
                     sum(point[1] for point in members) / len(members))
                    if members else center_point
                )
            if max(math.dist(a, b) for a, b in zip(
                    updated, centers, strict=True)) < 1e-4:
                centers = updated
                break
            centers = updated
        labels = [
            min(
                range(quantity),
                key=lambda i: (
                    (point[0] - centers[i][0]) ** 2
                    + (point[1] - centers[i][1]) ** 2,
                    i,
                ),
            )
            for point in samples
        ]
        add_verified(snap_to_cells(centers, labels))

    return layouts


def rank_options(total_cfm: float, application: str = "office_priv",
                 catalog: list[DiffuserModel] = ANDALOSIA_SUPPLY_CCD,
                 max_nc: float | None = None, max_dp_inwg: float = 0.20,
                 room: RoomLayout | None = None, delta_t_f: float | None = None,
                 max_qty: int = 24, top: int = 8,
                 total_load_btuh: float | None = None,
                 sensible_load_btuh: float | None = None,
                 strict: bool = False
                 ) -> list[DiffuserSelection]:
    """All catalog candidates, best first (strict=True drops any candidate that violates a rule).  Candidates with warnings=[] pass every rule.

    Search starts at the *minimum* count allowed by Table 4 CFM (ceiling
    height), 400 ft² coverage guidance, and L-shape wing coverage, then walks
    upward. Ranking prefers ADPI T50/L in 0.7–1.2 and the fewest / largest
    necks that still throw.
    """
    if not math.isfinite(total_cfm) or total_cfm <= 0:
        raise ValueError("total_cfm must be finite and > 0")
    _reject_total_load(total_load_btuh)
    sensible_load = sensible_load_btuh
    delta_t_f = _resolve_delta_t(total_cfm, delta_t_f, sensible_load)
    room = _with_load(room, sensible_load)
    if max_nc is None or max_nc <= 0:
        max_nc = APPLICATION_NC.get(application, 35)
    height = room.room_h_ft if room is not None else 10.0
    h_row, cfm_cap, dt_max, notes = ceiling_limits(height)
    extra = list(notes)
    delta_t_warning = (
        f"Supply ΔT {delta_t_f:.1f}°F exceeds Table 4 limit "
        f"{dt_max}°F for the {h_row} ft row."
        if delta_t_f is not None and delta_t_f > dt_max else None)
    if strict and delta_t_warning:
        return []

    min_qty_capacity = max(1, math.ceil(total_cfm / cfm_cap))
    min_qty_area = (
        max(1, math.ceil(room.floor_area_ft2 / MAX_AREA_PER_DIFFUSER_FT2))
        if room is not None else 1)
    min_qty_wings = _geometry_min_qty(room)
    qty_lo = max(1, min_qty_capacity, min_qty_area, min_qty_wings)

    qty_hi = max_qty
    if room is not None and room.floor_area_ft2 > 0:
        density_ceiling = max(
            qty_lo,
            math.floor(room.floor_area_ft2 / MIN_AREA_PER_DIFFUSER_FT2),
        )
        qty_hi = min(max_qty, density_ceiling)
    qty_hi = max(qty_lo, qty_hi)

    models = sorted(catalog, key=lambda model: -model.neck_dia_inch)
    cands: list[DiffuserSelection] = []
    for d in models:
        for n in range(qty_lo, qty_hi + 1):
            q = total_cfm / n
            v = q / d.neck_area_ft2
            if v < d.v[0] * 0.75 or v > d.v[-1] * 1.25:
                continue
            c = _evaluate(d, n, total_cfm, room, max_nc, max_dp_inwg,
                          cfm_cap, qty_lo)
            c.warnings = c.warnings + extra
            c.delta_t_f = delta_t_f
            c.delta_t_limit_f = float(dt_max)
            c.max_nc_limit = float(max_nc)
            c.rationale = _selection_rationale(c)
            c.rationale.update(tl_band=_band(d.kind, room),
                               violated_rules=violated_rule_ids(c.warnings))
            cands.append(c)
    if strict:
        cands = [c for c in cands if not c.rationale["violated_rules"]]
    cands.sort(key=_selection_rank_key)
    selected = cands[:top]
    if delta_t_warning:
        # This room-level violation is reported after ranking so it cannot
        # bias every candidate's otherwise-equivalent hard-warning score.
        for candidate in selected:
            candidate.warnings.append(delta_t_warning)
            candidate.rationale["violated_rules"] = violated_rule_ids(
                candidate.warnings)
    return selected


def select_diffuser(total_cfm: float, application: str = "office_priv",
                    catalog: list[DiffuserModel] = ANDALOSIA_SUPPLY_CCD,
                    max_nc: float | None = None, max_dp_inwg: float = 0.20,
                    room: RoomLayout | None = None,
                    delta_t_f: float | None = None,
                    total_load_btuh: float | None = None,
                    sensible_load_btuh: float | None = None,
                    strict: bool = False
                    ) -> DiffuserSelection:
    """Best option.  If nothing satisfies every rule the least-bad one is returned
    with the violated rules listed in .warnings (never silent)."""
    if room is not None and room.room_h_ft > max(CEILING_TABLE):
        raise ValueError(
            f"Ceiling height {room.room_h_ft:.1f} ft exceeds validated "
            f"Table 4 data (maximum {max(CEILING_TABLE)} ft); manufacturer "
            "review is required.")
    opts = rank_options(total_cfm, application, catalog, max_nc, max_dp_inwg,
                        room, delta_t_f, top=1,
                        total_load_btuh=total_load_btuh,
                        sensible_load_btuh=sensible_load_btuh, strict=strict)
    if not opts:
        raise RuntimeError("No catalog diffuser can handle this airflow"
                           + (" without violating a selection rule." if strict else "."))
    return opts[0]


@dataclass
class DiffuserLayoutResult:
    success: bool
    geometry: RoomGeometry
    requested_quantity: int
    recommended_quantity: int = 0
    placed_quantity: int = 0
    required_cfm: float = 0.0
    actual_total_cfm: float = 0.0
    selected_model: DiffuserSelection | None = None
    positions_m: list[tuple[float, float]] = field(default_factory=list)
    positions_ft: list[tuple[float, float]] = field(default_factory=list)
    performance: DiffuserSelection | None = None
    wall_clearance_ok: bool = False
    spacing_ok: bool = False
    failure_kind: str | None = None
    fallback_available: bool = False
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def select_layout_for_geometry(
        geometry: RoomGeometry, total_cfm: float,
        application: str = "office_priv",
        catalog: list[DiffuserModel] | None = None,
        max_nc: float | None = None, max_dp_inwg: float = 0.20,
        delta_t_f: float | None = None,
        min_wall_clearance_m: float = 0.30,
        min_spacing_m: float = 0.60,
        total_load_btuh: float | None = None,
        sensible_load_btuh: float | None = None,
        selected_option_index: int | None = None) -> DiffuserLayoutResult:
    """Select, place, and evaluate one complete layout for actual geometry."""
    errors = geometry.validate()
    if errors:
        return DiffuserLayoutResult(
            False, geometry, 0, required_cfm=total_cfm,
            failure_kind="invalid_geometry",
            errors=["Invalid room geometry: " + "; ".join(errors)])
    if total_cfm <= 0 or not math.isfinite(total_cfm):
        return DiffuserLayoutResult(
            False, geometry, 0, required_cfm=total_cfm,
            failure_kind="airflow_infeasible",
            errors=["Required airflow must be finite and greater than zero."])
    try:
        _reject_total_load(total_load_btuh)
        sensible_load = sensible_load_btuh
        delta_t_f = _resolve_delta_t(total_cfm, delta_t_f, sensible_load)
    except ValueError as exc:
        return DiffuserLayoutResult(
            False, geometry, 0, required_cfm=total_cfm,
            failure_kind="airflow_infeasible", errors=[str(exc)])

    active_catalog = ANDALOSIA_SUPPLY_CCD if catalog is None else catalog
    room = room_layout_from_geometry(geometry)
    height_row, _, delta_t_limit_f, height_notes = ceiling_limits(
        room.room_h_ft)
    if room.room_h_ft > max(CEILING_TABLE):
        return DiffuserLayoutResult(
            False, geometry, 0, required_cfm=total_cfm,
            failure_kind="unsupported_height",
            warnings=height_notes, errors=height_notes)
    if delta_t_f is not None and delta_t_f > delta_t_limit_f:
        message = (
            f"Calculated sensible ΔT {delta_t_f:.1f}°F exceeds the Table 4 "
            f"limit of {delta_t_limit_f}°F for the {height_row} ft row; "
            "review system airflow or supply-air temperature.")
        return DiffuserLayoutResult(
            False, geometry, 0, required_cfm=total_cfm,
            failure_kind="delta_t_exceeded", errors=[message])

    options = rank_options(
        total_cfm, application, active_catalog, max_nc, max_dp_inwg,
        room, delta_t_f, max_qty=24,
        # Bound expensive geometry placement while retaining alternate
        # quantities for the ranked catalog candidates.
        top=24,
        sensible_load_btuh=sensible_load)
    if not options:
        return DiffuserLayoutResult(
            False, geometry, 0, required_cfm=total_cfm,
            failure_kind="airflow_infeasible",
            errors=["No diffuser catalog option satisfies the airflow constraints."])

    if selected_option_index is not None:
        selected_option_index = max(0, min(int(selected_option_index), len(options) - 1))
        ranked = options[selected_option_index: selected_option_index + 1]
        remaining = [candidate for idx, candidate in enumerate(options)
                     if idx != selected_option_index]
        options = ranked + remaining

    recommended_quantity = options[0].qty
    feasible_layouts = []
    tested_options = set()
    placement_errors = []
    from placement_engine import is_orthogonal_polygon
    irregular_room = not is_orthogonal_polygon(geometry.vertices)
    is_rectangular_room = False
    if len(geometry.vertices) == 4:
        min_x, max_x, min_y, max_y = geometry.bounding_box
        corners = {
            (min_x, min_y), (max_x, min_y),
            (max_x, max_y), (min_x, max_y),
        }
        is_rectangular_room = all(
            any(math.dist(point, corner) <= 1e-8 for corner in corners)
            for point in geometry.vertices)
    # R-MIN-THROW is disabled by default: max(W,L)/2 has no basis in the docs.
    minimum_throw_ft = (room.max_dim_ft / 2.0 if is_rectangular_room
                        and rules_min_throw_prefilter_enabled() else 0.0)
    longest_throw_ft = max(option.throw_t50_ft for option in options)
    for option in options:
        if option.throw_t50_ft < minimum_throw_ft:
            continue
        quantity = option.qty
        option_key = (quantity, option.model, option.size_label)
        if option_key in tested_options:
            continue
        tested_options.add(option_key)
        model = next(
            (candidate for candidate in active_catalog
             if (candidate.model, candidate.size_label)
             == (option.model, option.size_label)),
            None,
        )
        if model is None:
            continue
        # Placement enforces physical clearances; verified layouts are ranked
        # by the selected model's throw-aware actual-polygon screening.
        face_half_extent_m = diffuser_face_half_extent_m(option)
        placement = place_diffusers_in_geometry(
            geometry, quantity, min_wall_clearance_m, min_spacing_m,
            throw_t50_m=ft_to_m(option.throw_t50_ft),
            face_half_extent_m=face_half_extent_m)
        if not placement.success:
            placement_errors.extend(placement.errors)
            continue
        positions_ft = [(m_to_ft(x), m_to_ft(y))
                        for x, y in placement.positions_m]
        try:
            evaluated, _ = evaluate_layout(
                total_cfm, positions_ft=positions_ft, room=room,
                application=application, catalog=[model], max_nc=max_nc,
                max_dp_inwg=max_dp_inwg, delta_t_f=delta_t_f, top=1,
                sensible_load_btuh=sensible_load)
        except (RuntimeError, ValueError) as exc:
            placement_errors.append(str(exc))
            continue
        feasible_layouts.append((evaluated, placement, positions_ft))

    configured_nc = (
        max_nc if max_nc is not None and max_nc > 0
        else APPLICATION_NC.get(application, 35))
    default_fully_compliant = any(
        candidate[0].adpi_ok
        and candidate[0].pressure_ok
        and candidate[0].nc_estimated <= configured_nc
        and not any("CFM/diffuser exceeds Table 4" in warning
                    for warning in candidate[0].warnings)
        and not any(warning.startswith("Neck velocity ")
                    for warning in candidate[0].warnings)
        for candidate in feasible_layouts
    )
    if irregular_room and not default_fully_compliant:
        for evaluated, placement, _ in tuple(feasible_layouts):
            if evaluated.adpi_ok:
                continue
            model = next(
                (candidate for candidate in active_catalog
                 if (candidate.model, candidate.size_label)
                 == (evaluated.model, evaluated.size_label)),
                None,
            )
            if model is None:
                continue
            face_half_extent_m = diffuser_face_half_extent_m(evaluated)
            wall_clearance_m = min_wall_clearance_m + face_half_extent_m
            default_positions = tuple(sorted(placement.positions_m))
            for alternative_positions in _alternative_irregular_layouts(
                    geometry, evaluated.qty, wall_clearance_m,
                    min_spacing_m, placement.positions_m):
                if tuple(alternative_positions) == default_positions:
                    continue
                positions_ft = [
                    (m_to_ft(x), m_to_ft(y))
                    for x, y in alternative_positions
                ]
                try:
                    alternative, _ = evaluate_layout(
                        total_cfm, positions_ft=positions_ft, room=room,
                        application=application, catalog=[model],
                        max_nc=max_nc, max_dp_inwg=max_dp_inwg,
                        delta_t_f=delta_t_f, top=1,
                        sensible_load_btuh=sensible_load)
                except (RuntimeError, ValueError) as exc:
                    placement_errors.append(str(exc))
                    continue
                fully_compliant_alternative = (
                    alternative.adpi_ok
                    and alternative.pressure_ok
                    and alternative.nc_estimated <= configured_nc
                    and not any(
                        "CFM/diffuser exceeds Table 4" in warning
                        for warning in alternative.warnings
                    )
                    and not any(
                        warning.startswith("Neck velocity ")
                        for warning in alternative.warnings
                    )
                )
                if fully_compliant_alternative:
                    placement_result = GeometryPlacementResult(
                        True, evaluated.qty,
                        positions_m=alternative_positions,
                        wall_clearance_ok=True,
                        spacing_ok=True,
                        throw_t50_m=ft_to_m(alternative.throw_t50_ft),
                    )
                    feasible_layouts.append(
                        (alternative, placement_result, positions_ft))

    if not feasible_layouts:
        if (minimum_throw_ft > 0
                and all(option.throw_t50_ft < minimum_throw_ft
                        for option in options)):
            return DiffuserLayoutResult(
                False, geometry, recommended_quantity,
                recommended_quantity=recommended_quantity,
                required_cfm=total_cfm, failure_kind="insufficient_throw",
                errors=[
                    (f"No catalog option provides the required minimum T50 "
                    f"throw of {minimum_throw_ft:.1f} ft (half the room's "
                    f"{room.max_dim_ft:.1f} ft longest dimension); the "
                    f"longest available T50 is {longest_throw_ft:.1f} ft.")
                ])
        return DiffuserLayoutResult(
            False, geometry, recommended_quantity,
            recommended_quantity=recommended_quantity,
            required_cfm=total_cfm,
            failure_kind="geometry_infeasible",
            errors=[
                (f"Geometry-infeasible: no complete layout could place the "
                f"recommended {recommended_quantity} diffusers or an "
                "airflow-feasible alternative."),
                ("Note: placement requires each diffuser inside the room "
                "polygon with wall clearance. In irregular rooms this may "
                "be unsatisfiable — consider a longer-throw outlet or "
                "place diffusers manually in Room Designer."),
                *placement_errors[:3],
            ])

    selection, placement, positions_ft = min(
        feasible_layouts,
        key=lambda item: _selection_rank_key(item[0]))
    fully_compliant = [
        candidate for candidate in feasible_layouts
        if candidate[0].adpi_ok
        and candidate[0].pressure_ok
        and candidate[0].nc_estimated <= configured_nc
        and not any("CFM/diffuser exceeds Table 4" in warning
                    for warning in candidate[0].warnings)
        and not any(warning.startswith("Neck velocity ")
                    for warning in candidate[0].warnings)
    ]
    if not fully_compliant:
        any_noise_compliant = any(
            candidate[0].nc_estimated <= configured_nc
            for candidate in feasible_layouts)
        acoustic_failure = not any_noise_compliant
        reason = (
            f"No candidate meets the configured NC limit of "
            f"{configured_nc:.0f}; no acoustically compliant layout is available."
            if acoustic_failure else
            "No candidate meets all T50/L, Table 4, pressure, and acoustic "
            "screening criteria."
        )
        status = (
            "no_acoustically_compliant_option"
            if acoustic_failure else "no_fully_compliant_option"
        )
        return DiffuserLayoutResult(
            False, geometry, recommended_quantity,
            recommended_quantity=recommended_quantity,
            placed_quantity=len(positions_ft),
            required_cfm=total_cfm, actual_total_cfm=total_cfm,
            selected_model=selection, positions_m=placement.positions_m,
            positions_ft=positions_ft, wall_clearance_ok=placement.wall_clearance_ok,
            spacing_ok=placement.spacing_ok, fallback_available=True,
            performance=selection, failure_kind=status,
            warnings=list(selection.warnings),
            errors=[reason, selection.rationale.get("summary", "")],
        )
    selection, placement, positions_ft = min(
        fully_compliant, key=lambda item: _selection_rank_key(item[0]))
    result = DiffuserLayoutResult(
        False, geometry, recommended_quantity,
        recommended_quantity=recommended_quantity, required_cfm=total_cfm,
        selected_model=selection, warnings=list(selection.warnings),
        failure_kind="geometry_infeasible")
    result.success = True
    result.failure_kind = None
    result.placed_quantity = len(positions_ft)
    result.actual_total_cfm = total_cfm
    result.positions_m = placement.positions_m
    result.positions_ft = positions_ft
    result.selected_model = selection
    result.performance = selection
    result.wall_clearance_ok = placement.wall_clearance_ok
    result.spacing_ok = placement.spacing_ok
    result.warnings = list(selection.warnings)
    if selection.qty != recommended_quantity:
        result.warnings.insert(
            0,
            f"Geometry-aware selection used {selection.qty} diffusers instead "
            f"of the nominal {recommended_quantity}-diffuser recommendation; "
            "the full required airflow is retained.")
    return result


def wall_proximity_advice(sel: DiffuserSelection, distance_to_wall_ft: float) -> str:
    """4-way vs 3-way: does the throw overshoot a wall at this distance?"""
    _, hi = ADPI_BANDS.get("square", (0.7, 1.2))
    r = sel.throw_t50_ft / max(distance_to_wall_ft, 0.1)
    if r > hi:
        return (f"T50/L = {r:.2f} > {hi}: jet would hit the wall – block that side "
                f"(use 3-way 3SCD) or move the diffuser {sel.throw_t50_ft/hi - distance_to_wall_ft:.1f} ft away.")
    return f"T50/L = {r:.2f} ≤ {hi}: 4-way is fine at this distance."


def format_report(sel: DiffuserSelection, room: RoomLayout, total_cfm: float,
                  application: str) -> str:
    ac = ach(total_cfm, room)
    tl_band = (sel.rationale.get("tl_band") or (0.7, 1.2))
    verification_status = sel.rationale.get(
        "verification_status", "ASHRAE-aligned screening; ADPI not verified")
    lines = [
        f"═══ Al-Andalosia Diffuser Selection — {application} ═══",
        "Manufacturer         : AL-ANDALOSIA FOR AIR OUTLETS",
        f"Verification status   : {verification_status}",
        "Engineering basis     : ASHRAE HVAC Applications Ch.57; "
        "Fundamentals Ch.20",
        f"Total airflow        : {total_cfm:,.0f} CFM",
        f"Room Dimensions      : {room.room_w_ft:.1f} × {room.room_l_ft:.1f} × {room.room_h_ft:.1f} ft ({room.floor_area_ft2:,.0f} ft²)",
        f"Air changes per hour : {ac:.1f} ACH",
        f"Layout               : {sel.rows} × {sel.cols}  (L = {sel.char_L_ft:.1f} ft)",
        (f"T50/L screening     : {sel.adpi_ratio_min:.2f} – {sel.adpi_ratio:.2f}  "
        f"(screening band {tl_band[0]}–{tl_band[1]}, "
        f"{'within band' if sel.adpi_ok else 'review'}; ADPI not verified)"),
        "Supply ΔT            : "
        + (f"{sel.delta_t_f:.1f}°F (Table 4 max {sel.delta_t_limit_f:.0f}°F)"
           if sel.delta_t_f is not None and sel.delta_t_limit_f is not None
           else "n/a"),
        "",
        "── Selected Al-Andalosia Model ──",
        f"Model / Type         : {sel.model} ({sel.size_label})",
        f"Quantity             : {sel.qty} unit(s)",
        f"Airflow per diffuser : {sel.cfm_per_unit:,.0f} CFM",
        f"Neck velocity        : {sel.neck_velocity_fpm:,.0f} FPM",
        f"Catalog Total ΔP     : {sel.pressure_drop_inwg:.4f} in.wg "
        f"({'OK' if sel.pressure_ok else 'REVIEW'}; limit "
        f"{sel.max_dp_limit_inwg:.2f} in.wg)",
        "Pressure basis       : catalog total-pressure loss; not system static pressure",
        f"Sound (catalog)      : NC {sel.nc_label}",
        f"Throw Range (T100-T50): {sel.throw_t100_ft:.1f} - {sel.throw_t50_ft:.1f} ft",
        f"Max Spacing          : {sel.spacing_max_ft:.1f} ft",
    ]
    for w in sel.warnings:
        lines.append(f"⚠ {w}")
    return "\n".join(lines)
