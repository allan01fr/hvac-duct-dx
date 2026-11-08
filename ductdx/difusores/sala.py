"""Sala, malha e verificações de jatos (movido de diffuser_calculator.py)."""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace

from ductdx.difusores.conversoes import m2_to_ft2, m_to_ft
from ductdx.difusores.geometria_ambiente import RoomGeometry
from ductdx.difusores.regras import ADPI_BANDS, rules_load_w_m2, rules_tl_band


# ─────────────────────────────────────────────────────────────
#  Room / grid
# ─────────────────────────────────────────────────────────────
@dataclass
class RoomLayout:
    room_w_ft: float
    room_l_ft: float
    room_h_ft: float = 10.0
    polygon_ft: list[tuple[float, float]] | None = None
    area_ft2_override: float | None = None
    geometry: RoomGeometry | None = None
    cooling_load_w_m2: float | None = None   # sensible load / floor area (R-TL-BAND)

    @classmethod
    def from_metric(cls, w_m: float, l_m: float, h_m: float = 3.0) -> RoomLayout:
        return cls(m_to_ft(w_m), m_to_ft(l_m), m_to_ft(h_m))

    @classmethod
    def from_geometry(cls, geometry: RoomGeometry) -> RoomLayout:
        errors = geometry.validate()
        if errors:
            raise ValueError("Invalid room geometry: " + "; ".join(errors))
        min_x, max_x, min_y, max_y = geometry.bounding_box
        return cls(
            room_w_ft=round(m_to_ft(max_x - min_x), 9),
            room_l_ft=round(m_to_ft(max_y - min_y), 9),
            room_h_ft=m_to_ft(geometry.height_m),
            polygon_ft=[(m_to_ft(x), m_to_ft(y))
                        for x, y in geometry.vertices],
            area_ft2_override=m2_to_ft2(geometry.area_m2),
            geometry=geometry,
        )

    @property
    def floor_area_ft2(self) -> float:
        if self.area_ft2_override is not None:
            return self.area_ft2_override
        return self.room_w_ft * self.room_l_ft
    @property
    def volume_ft3(self) -> float: return self.floor_area_ft2 * self.room_h_ft
    @property
    def max_dim_ft(self) -> float: return max(self.room_w_ft, self.room_l_ft)


def ach(cfm: float, room: RoomLayout) -> float:
    return (cfm * 60.0) / max(1.0, room.volume_ft3)


@dataclass
class Grid:
    rows: int
    cols: int
    cell_w: float
    cell_l: float

    @property
    def L_min(self) -> float: return min(self.cell_w, self.cell_l) / 2.0
    @property
    def L_max(self) -> float: return max(self.cell_w, self.cell_l) / 2.0
    @property
    def aspect(self) -> float: return max(self.cell_w, self.cell_l) / min(self.cell_w, self.cell_l)


def best_grid(room: RoomLayout, n: int) -> Grid:
    """rows×cols == n with cells as square as possible (width = x axis)."""
    best = None
    for rows in range(1, n + 1):
        if n % rows:
            continue
        cols = n // rows
        g = Grid(rows, cols, room.room_w_ft / cols, room.room_l_ft / rows)
        if best is None or g.aspect < best.aspect:
            best = g
    return best


def grid_positions(room: RoomLayout, n: int, throw_t50_ft: float | None = None
                   ) -> list[tuple[float, float]]:
    """Cell centres of the same grid used by select_diffuser (x along width, y along length)."""
    if n <= 0:
        return []
    g = best_grid(room, n)
    return [(round(g.cell_w * (j + 0.5), 2), round(g.cell_l * (i + 0.5), 2))
            for i in range(g.rows) for j in range(g.cols)]


def _band(kind: str, room: RoomLayout | None) -> tuple[float, float]:
    """R-TL-BAND: T50/L band for the room's cooling load (fallback 0.7-1.2)."""
    if room is None:
        return ADPI_BANDS.get(kind, ADPI_BANDS["square"])
    return rules_tl_band(getattr(room, "cooling_load_w_m2", None))


def _with_load(room: RoomLayout | None, sensible_btuh: float | None
               ) -> RoomLayout | None:
    if room is None:
        return None
    load = rules_load_w_m2(sensible_btuh, room.floor_area_ft2)
    return replace(room, cooling_load_w_m2=load) if load is not None else room


_RULE_PREFIXES = (
    ("Neck velocity", "R-CATALOG-RANGE"), ("ΔP ", "R-DP"),
    ("Noise NC", "R-NC"), ("Supply ΔT", "R-TABLE4"),
    ("T50/L", "R-TL-BAND"), ("Only ", "R-MIN-QTY"),
    ("Potential jet interaction", "R-JET-COLLISION"),
)


def violated_rule_ids(warnings: Sequence[str]) -> list[str]:
    ids: list[str] = []
    for w in warnings:
        rid = next((r for pre, r in _RULE_PREFIXES if w.startswith(pre)), None)
        if rid is None and "exceeds Table 4" in w:
            rid = "R-TABLE4"
        if rid is None and ("too dense" in w or "rule of thumb" in w):
            rid = "R-AREA"
        if rid and rid not in ids:
            ids.append(rid)
    return ids


def jet_collision_warnings(
        positions_ft: Sequence[tuple[float, float]],
        throw_t50_ft: Sequence[float],
        ) -> list[str]:
    """Screen possible jet-envelope overlap; this is not an air-velocity check.

    The supplied catalog has no verified directional-jet model for this path.
    Therefore the screen only flags pairs whose radial T50 proxy envelopes
    overlap (center distance < sum of the two T50 values).  It deliberately
    does not infer jet direction, occupied-zone velocity, or comfort compliance.
    """
    if len(positions_ft) != len(throw_t50_ft):
        raise ValueError("positions_ft and throw_t50_ft must have equal lengths")
    if any(
            len(point) != 2
            or not all(math.isfinite(float(value)) for value in point)
            for point in positions_ft):
        raise ValueError("positions_ft must contain finite 2D points")
    if any(not math.isfinite(float(throw)) or float(throw) < 0
           for throw in throw_t50_ft):
        raise ValueError("throw_t50_ft must contain finite non-negative values")

    warnings: list[str] = []
    for i in range(len(positions_ft)):
        for j in range(i + 1, len(positions_ft)):
            distance = math.dist(positions_ft[i], positions_ft[j])
            envelope = float(throw_t50_ft[i]) + float(throw_t50_ft[j])
            if distance < envelope:
                warnings.append(
                    "Potential jet interaction between diffusers "
                    f"{i + 1} and {j + 1}: center distance {distance:.2f} ft "
                    f"is less than the T50 envelope sum {envelope:.2f} ft; "
                    "direction and occupied-zone velocity are not verified.")
    return warnings


def adpi_check(throw_t50_ft: float, characteristic_L_ft: float,
               kind: str = "square") -> tuple[bool, float]:
    """Screen T50/L against the design band; this does not calculate ADPI."""
    if characteristic_L_ft <= 0:
        return False, float("inf")
    lo, hi = ADPI_BANDS.get(kind, ADPI_BANDS["square"])
    r = throw_t50_ft / characteristic_L_ft
    return (lo <= r <= hi), round(r, 2)


def room_layout_from_cad(cad_room: dict[str, object]) -> RoomLayout:
    """Adapt legacy CAD wall data to the feet-based calculator boundary."""
    geometry = RoomGeometry.from_dict(cad_room)
    return room_layout_from_geometry(geometry)


def room_layout_from_geometry(geometry: RoomGeometry) -> RoomLayout:
    """Convert validated metric geometry to the legacy feet-based API once."""
    errors = geometry.validate()
    if errors:
        raise ValueError("Invalid room geometry: " + "; ".join(errors))
    return RoomLayout.from_geometry(geometry)
