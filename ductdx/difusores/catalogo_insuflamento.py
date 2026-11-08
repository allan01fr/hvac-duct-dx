"""Catálogo de difusores de insuflamento e desempenho (movido de diffuser_calculator.py)."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ductdx.difusores import dados_catalogo as _cd
from ductdx.difusores.regras import BAND_LABEL, BAND_NC


# ─────────────────────────────────────────────────────────────
#  Model + interpolation
# ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class DiffuserModel:
    model: str
    kind: str
    size_label: str
    neck_dia_inch: float
    neck_area_ft2: float
    v: tuple[float, ...]            # tabulated neck velocities (fpm)
    cfm: tuple[float, ...]
    pt: tuple[float, ...]           # total pressure (in.wg)
    t100: tuple[float, ...]
    t50: tuple[float, ...]
    t50_back: tuple[float, ...]     # 3-way back-side throw (= t50 otherwise)
    nc: tuple[float, ...] | None = None      # numeric NC (round)
    band: tuple[int, ...] | None = None      # colour band (square)

    @property
    def cfm_min(self) -> float: return self.cfm[0]
    @property
    def cfm_max(self) -> float: return self.cfm[-1]


def _interp(x: float, xs: Sequence[float], ys: Sequence[float]) -> float:
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for i in range(len(xs) - 1):
        if xs[i] <= x <= xs[i + 1]:
            f = (x - xs[i]) / (xs[i + 1] - xs[i])
            return ys[i] + f * (ys[i + 1] - ys[i])
    return ys[-1]


def _build() -> tuple[list[DiffuserModel], list[DiffuserModel], list[DiffuserModel]]:
    ccd, s4, s3 = [], [], []
    for s, d in sorted(_cd.CCD.items()):
        ccd.append(DiffuserModel(
            f"CCD-{s}", "round", f'{s}"', s, d["area"], tuple(_cd.VC),
            tuple(d["cfm"]), tuple(d["pt"]),
            tuple(float(a) for a, _ in d["th"]), tuple(float(b) for _, b in d["th"]),
            tuple(float(b) for _, b in d["th"]), nc=tuple(d["nc"])))
    for s, d in sorted(_cd.SQUARE.items()):
        cfm = tuple(float(c) for c in d["cfm"])
        neck_area = d["area"]
        s4.append(DiffuserModel(
            f"4SCD-{s}", "square", f'{s}×{s}"', s, neck_area, tuple(_cd.VEL8), cfm,
            tuple(_cd.PT8), tuple(float(a) for a, _ in d["th4"]),
            tuple(float(b) for _, b in d["th4"]), tuple(float(b) for _, b in d["th4"]),
            band=tuple(d["band4"])))
        s3.append(DiffuserModel(
            f"3SCD-{s}", "square3", f'{s}×{s}"', s, neck_area, tuple(_cd.VEL8), cfm,
            tuple(_cd.PT8), tuple(float(a) for a, _ in d["tha"]),
            tuple(float(b) for _, b in d["tha"]), tuple(float(b) for _, b in d["thb"]),
            band=tuple(d["band3"])))
    return ccd, s4, s3


ANDALOSIA_SUPPLY_CCD, ANDALOSIA_SUPPLY_4SCD, ANDALOSIA_SUPPLY_3SCD = _build()
SUPPLY_CATALOG = ANDALOSIA_SUPPLY_CCD


def get_catalog(type_label: str) -> list[DiffuserModel]:
    t = (type_label or "").lower()
    if "circular" in t or "ccd" in t or "round" in t:
        return ANDALOSIA_SUPPLY_CCD
    if "3" in t:
        return ANDALOSIA_SUPPLY_3SCD
    return ANDALOSIA_SUPPLY_4SCD


@dataclass
class Perf:
    v_fpm: float
    pt: float
    t100: float
    t50: float
    t50_back: float
    nc: float
    nc_label: str
    in_range: bool


def performance(d: DiffuserModel, q_each: float) -> Perf:
    """Interpolate the catalog table at the actual airflow (CFM)."""
    v = q_each / d.neck_area_ft2
    # tabulated CFM uses the same area, so interpolate on velocity
    pt = _interp(v, d.v, d.pt)
    t100 = _interp(v, d.v, d.t100)
    t50 = _interp(v, d.v, d.t50)
    t50b = _interp(v, d.v, d.t50_back)
    if d.nc is not None:
        nc = _interp(v, d.v, d.nc)
        label = "<20" if nc < 20 else f"{nc:.0f}"
        nc_out = max(nc, 20.0) if nc < 20 else nc
    else:
        i = max(0, min(len(d.v) - 2, sum(1 for x in d.v if x <= v) - 1))
        b = max(d.band[i], d.band[i + 1]) if v > d.v[0] else d.band[0]
        nc_out, label = BAND_NC[b], BAND_LABEL[b]
    ok = d.v[0] <= v <= d.v[-1]
    return Perf(v, pt, t100, t50, t50b, nc_out, label, ok)


def calculate_performance(d: DiffuserModel, q_actual: float):
    """Backward-compatible: (ΔP, T100, T50, NC)."""
    p = performance(d, q_actual)
    return round(p.pt, 4), round(p.t100, 1), round(p.t50, 1), round(p.nc, 1)


def neck_velocity(cfm: float, neck_area_ft2: float) -> float:
    if neck_area_ft2 <= 0:
        raise ValueError("Neck area must be positive")
    return cfm / neck_area_ft2
