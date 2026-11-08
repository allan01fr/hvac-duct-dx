"""Cálculo de ESP (pressão estática externa). Movido de main.py sem alterar corpo."""
from dataclasses import dataclass, field

FRICTION_PER_METER = 0.015

FITTINGS_PRESSURE = {
    "elbow_90": 0.010,
    "elbow_45": 0.005,
    "tee": 0.015,
    "reducer": 0.008,
    "transition": 0.010,
}

ACCESSORIES_PRESSURE = {
    "filter_standard": 0.08,
    "filter_hepa": 0.25,
    "filter_washable": 0.05,
    "cooling_coil": 0.10,
    "heating_coil": 0.06,
    "damper_manual": 0.02,
    "damper_motorized": 0.05,
    "diffuser": 0.03,
    "grille_return": 0.04,
    "fresh_air_intake": 0.05,
    "vav_box": 0.15,
}

ESP_PRESETS = {
    "Split System (Single Room)": {
        "range": (0.05, 0.12),
        "default": 0.08,
        "desc": "Very short ductwork or no ductwork",
    },
    "Residential - Apartment / Villa": {
        "range": (0.10, 0.18),
        "default": 0.14,
        "desc": "Medium ductwork with a limited number of diffusers",
    },
    "Office / Commercial Shop": {
        "range": (0.15, 0.25),
        "default": 0.20,
        "desc": "Medium ductwork + filter + fresh air",
    },
    "Hotel / Hospital": {
        "range": (0.25, 0.35),
        "default": 0.30,
        "desc": "Long ductwork + high-efficiency filter + fresh air",
    },
    "Mall / Large Building": {
        "range": (0.30, 0.45),
        "default": 0.38,
        "desc": "Long ductwork + VAV + filters",
    },
}


@dataclass
class ESPInput:
    supply_duct_length_m: float = 0.0
    return_duct_length_m: float = 0.0
    elbow_90_count: int = 0
    elbow_45_count: int = 0
    tee_count: int = 0
    reducer_count: int = 0
    transition_count: int = 0
    accessories: list[str] = field(default_factory=list)
    custom_additions: float = 0.0


@dataclass
class ESPResult:
    supply_friction: float = 0.0
    return_friction: float = 0.0
    fittings_total: float = 0.0
    accessories_total: float = 0.0
    custom: float = 0.0
    total: float = 0.0
    breakdown: dict = field(default_factory=dict)


def calculate_esp(data: ESPInput) -> ESPResult:
    result = ESPResult()
    result.supply_friction = data.supply_duct_length_m * FRICTION_PER_METER
    result.return_friction = data.return_duct_length_m * FRICTION_PER_METER
    result.fittings_total = (
        data.elbow_90_count * FITTINGS_PRESSURE["elbow_90"]
        + data.elbow_45_count * FITTINGS_PRESSURE["elbow_45"]
        + data.tee_count * FITTINGS_PRESSURE["tee"]
        + data.reducer_count * FITTINGS_PRESSURE["reducer"]
        + data.transition_count * FITTINGS_PRESSURE["transition"]
    )
    result.accessories_total = sum(
        ACCESSORIES_PRESSURE.get(a, 0.0) for a in data.accessories
    )
    result.custom = data.custom_additions
    result.total = (
        result.supply_friction
        + result.return_friction
        + result.fittings_total
        + result.accessories_total
        + result.custom
    )
    result.breakdown = {
        "Supply Duct Friction": result.supply_friction,
        "Return Duct Friction": result.return_friction,
        "Fittings": result.fittings_total,
        "Accessories": result.accessories_total,
        "Custom": result.custom,
    }
    return result


def suggest_esp_from_cfm(
    cfm: float, app_type: str = "Office / Commercial Shop"
) -> float:
    base = ESP_PRESETS.get(app_type, {}).get("default", 0.20)
    if cfm < 200:
        return base * 0.6
    elif cfm < 400:
        return base * 0.8
    elif cfm < 800:
        return base
    elif cfm < 1500:
        return base * 1.2
    else:
        return base * 1.4
