"""Geometria de polígonos usada pelos difusores (movido de diffuser_calculator.py)."""
from __future__ import annotations

import math
from collections.abc import Sequence


def polygon_area(points: Sequence[tuple[float, float]]) -> float:
    if len(points) < 3:
        return 0.0
    return abs(sum(
        points[i][0] * points[(i + 1) % len(points)][1]
        - points[(i + 1) % len(points)][0] * points[i][1]
        for i in range(len(points))
    )) / 2.0


def polygon_bounds(points: Sequence[tuple[float, float]]
                   ) -> tuple[float, float, float, float]:
    if not points:
        return 0.0, 0.0, 0.0, 0.0
    xs, ys = zip(*points, strict=True)
    return min(xs), max(xs), min(ys), max(ys)


def point_in_polygon(x: float, y: float,
                     polygon: Sequence[tuple[float, float]]) -> bool:
    if len(polygon) < 3:
        return False
    inside = False
    j = len(polygon) - 1
    for i, (xi, yi) in enumerate(polygon):
        xj, yj = polygon[j]
        if ((yi > y) != (yj > y)) and (
                x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def distance_to_polygon_walls(x: float, y: float,
                              polygon: Sequence[tuple[float, float]]) -> float:
    if len(polygon) < 2:
        return 0.0
    return min(
        _distance_to_segment(x, y, polygon[i], polygon[(i + 1) % len(polygon)])
        for i in range(len(polygon))
    )



def _distance_to_segment(x: float, y: float, a: tuple[float, float],
                         b: tuple[float, float]) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length_squared = dx * dx + dy * dy
    if length_squared == 0:
        return math.hypot(x - a[0], y - a[1])
    t = max(0.0, min(1.0, ((x - a[0]) * dx + (y - a[1]) * dy)
                     / length_squared))
    return math.hypot(x - (a[0] + t * dx), y - (a[1] + t * dy))


def _ray_distance_to_polygon(x: float, y: float, dx: float, dy: float,
                             polygon: Sequence[tuple[float, float]]) -> float:
    """Distance from an interior point to the nearest positive ray/boundary intersection."""
    distance = float("inf")
    for i, a in enumerate(polygon):
        b = polygon[(i + 1) % len(polygon)]
        edge = (b[0] - a[0], b[1] - a[1])
        offset = (a[0] - x, a[1] - y)
        denominator = dx * edge[1] - dy * edge[0]
        if abs(denominator) <= 1e-12:
            continue
        ray_t = (offset[0] * edge[1] - offset[1] * edge[0]) / denominator
        edge_t = (offset[0] * dy - offset[1] * dx) / denominator
        if ray_t > 1e-9 and -1e-9 <= edge_t <= 1.0 + 1e-9:
            distance = min(distance, ray_t)
    if math.isinf(distance):
        raise ValueError("No positive polygon boundary crossing found for ray")
    return distance
