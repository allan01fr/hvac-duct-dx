# Casos de caracterização dos difusores (diffuser_calculator.py). Um assunto: o que o módulo devolve hoje.
import dataclasses
import enum
import math
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import diffuser_calculator as dc
from room_geometry import RoomGeometry

RETANGULO = RoomGeometry.from_vertices([(0, 0), (6, 0), (6, 5), (0, 5)], 3.0)
EM_L = RoomGeometry.from_vertices([(0, 0), (8, 0), (8, 4), (4, 4), (4, 7), (0, 7)], 2.8)


def _sala():
    return dc.RoomLayout(20, 20, room_h_ft=10)


CASOS = {
    "select_diffuser_800": lambda: dc.select_diffuser(800),
    "select_diffuser_sala": lambda: dc.select_diffuser(
        1200, room=dc.RoomLayout(20, 20, room_h_ft=10), sensible_load_btuh=12000),
    "rank_options_1500": lambda: dc.rank_options(
        1500, room=dc.RoomLayout(30, 25, room_h_ft=9), top=5),
    "layout_retangulo": lambda: dc.select_layout_for_geometry(
        RETANGULO, 600, sensible_load_btuh=10000),
    "layout_em_L": lambda: dc.select_layout_for_geometry(
        EM_L, 900, sensible_load_btuh=10000),
    "evaluate_layout_4": lambda: dc.evaluate_layout(
        1000, positions_ft=[(5, 5), (15, 5), (5, 15), (15, 15)],
        room=dc.RoomLayout(20, 20, room_h_ft=10), sensible_load_btuh=10800),
    "retorno_1000": lambda: dc.select_return_diffusers(1000),
    "vcd_300x200": lambda: dc.vcd_select(300, 200),
    "vcd_1250x610": lambda: dc.vcd_select(1250, 610),
    "rvcd_10_400": lambda: dc.rvcd_select(10, 400),
    "rvcd_14_1200_mp": lambda: dc.rvcd_select(14, 1200, "MP"),
    "porta_500": lambda: dc.access_door_select(500),
    "porta_3000": lambda: dc.access_door_select(3000),
    "posicionar_motor": lambda: dc.place_diffusers_in_geometry(RETANGULO, 4),
    "posicionar_legado_qtd0": lambda: dc.place_diffusers_in_geometry(RETANGULO, 0),
    "posicionar_legado_folga_negativa": lambda: dc.place_diffusers_in_geometry(
        RETANGULO, 4, min_wall_clearance_m=-1),
    "relatorio_texto": lambda: dc.format_report(
        dc.select_diffuser(800, room=_sala()), _sala(), 800, "office_priv"),
}


def para_json(obj):
    if isinstance(obj, enum.Enum):
        return obj.name
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {c.name: para_json(getattr(obj, c.name)) for c in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        return {str(k): para_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [para_json(v) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj):
            return "nan"
        if math.isinf(obj):
            return "inf" if obj > 0 else "-inf"
        return obj
    if obj is None or isinstance(obj, (bool, int, str)):
        return obj
    return {"__tipo__": type(obj).__name__, "repr": repr(obj)}


def executar(nome):
    try:
        return {"ok": para_json(CASOS[nome]())}
    except Exception as e:  # noqa: BLE001 # o erro também é comportamento a caracterizar
        return {"erro": [type(e).__name__, str(e)]}
