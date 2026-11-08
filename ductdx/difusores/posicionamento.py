"""Posicionamento de difusores em geometria (movido de diffuser_calculator.py)."""
from __future__ import annotations

import logging
import math
import warnings
from collections.abc import Sequence
from dataclasses import dataclass, field

from ductdx.difusores.conversoes import ft_to_m
from ductdx.difusores.geometria import (
    distance_to_polygon_walls,
    point_in_polygon,
    polygon_bounds,
)
from ductdx.difusores.geometria_ambiente import RoomGeometry
from ductdx.difusores.sala import RoomLayout, best_grid

logger = logging.getLogger(__name__)



def distribute_polygon_positions(polygon: Sequence[tuple[float, float]],
                                 quantity: int,
                                 min_wall_distance: float = 0.30,
                                 min_spacing: float = 0.0
                                 ) -> list[tuple[float, float]]:
    """Place an exact quantity inside a valid polygon or return no layout."""
    from ductdx.difusores.motor_posicionamento import validate_polygon, verify_placement

    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise ValueError("quantity must be a positive integer")
    try:
        wall_distance = float(min_wall_distance)
        spacing = float(min_spacing)
    except (TypeError, ValueError) as exc:
        raise ValueError("Wall clearance and spacing must be numeric") from exc
    if (not math.isfinite(wall_distance) or wall_distance < 0
            or not math.isfinite(spacing) or spacing < 0):
        raise ValueError(
            "Wall clearance and spacing must be finite and non-negative")
    try:
        points = []
        for point in polygon:
            if isinstance(point, (str, bytes)) or len(point) != 2:
                raise ValueError
            points.append((float(point[0]), float(point[1])))
    except (TypeError, ValueError, IndexError) as exc:
        raise ValueError(
            "polygon must contain numeric (x, y) vertices") from exc
    valid_polygon, polygon_diagnostic = validate_polygon(points)
    if not valid_polygon:
        raise ValueError(
            "Invalid room polygon: "
            + str(polygon_diagnostic.get("reason", "invalid polygon")))

    engine_spacing = spacing if spacing > 0 else 0.01
    try:
        from ductdx.difusores.motor_posicionamento import (
            PlacementStatus,
            place_diffusers,
        )
        engine = place_diffusers(
            polygon=points,
            count=quantity,
            wall_clearance_m=wall_distance,
            min_spacing_m=engine_spacing,
            strategy="auto",
        )
        contained = [
            (float(x), float(y)) for x, y in engine.positions_m
            if point_in_polygon(float(x), float(y), points)
        ]
        if (engine.status == PlacementStatus.SUCCESS
                and len(contained) == quantity
                and verify_placement(
                    points, contained, wall_distance, engine_spacing).valid):
            return contained
    except (ImportError, AttributeError, TypeError, ValueError, RuntimeError) as exc:
        logger.warning("Placement engine unavailable; using legacy placement: %s", exc)

    min_x, max_x, min_y, max_y = polygon_bounds(points)
    width, length = max_x - min_x, max_y - min_y
    if width <= 0 or length <= 0:
        return []
    if quantity > 160 * 160:
        return []

    best = None
    for candidate_rows in range(1, quantity + 1):
        if quantity % candidate_rows:
            continue
        candidate_cols = quantity // candidate_rows
        cell_w = width / candidate_cols
        cell_l = length / candidate_rows
        aspect = max(cell_w, cell_l) / min(cell_w, cell_l)
        if best is None or aspect < best[0]:
            best = (aspect, candidate_rows, candidate_cols)
    _, rows, cols = best
    ideals = [
        (min_x + (col + 0.5) * width / cols,
         min_y + (row + 0.5) * length / rows)
        for row in range(rows) for col in range(cols)
    ][:quantity]

    divisions = max(15, min(60, math.ceil(max(width, length) / 0.25)))
    valid = []
    for row in range(divisions):
        y = min_y + (row + 0.5) * length / divisions
        for col in range(divisions):
            x = min_x + (col + 0.5) * width / divisions
            if (point_in_polygon(x, y, points)
                    and distance_to_polygon_walls(x, y, points) + 1e-9
                    >= wall_distance):
                rounded = (round(x, 3), round(y, 3))
                if (point_in_polygon(*rounded, points)
                        and distance_to_polygon_walls(*rounded, points) + 1e-9
                        >= wall_distance):
                    valid.append(rounded)

    if not valid:
        return []

    unassigned = set(valid)
    placed = []
    for ideal in ideals:
        ideal_valid = (
            point_in_polygon(*ideal, points)
            and distance_to_polygon_walls(*ideal, points) + 1e-9
            >= wall_distance
            and all(math.dist(ideal, other) + 1e-9 >= engine_spacing
                    for other in placed)
        )
        if ideal_valid:
            candidate = ideal
            unassigned.discard(candidate)
        else:
            available = [
                candidate for candidate in unassigned
                if all(math.dist(candidate, other) + 1e-9 >= engine_spacing
                       for other in placed)
            ]
            if not available:
                return []
            candidate = min(
                available,
                key=lambda point: math.dist(point, ideal),
            )
            unassigned.discard(candidate)
        placed.append(candidate)
    if len(placed) != quantity:
        return []
    verification = verify_placement(
        points, placed, wall_distance, engine_spacing)
    return placed if verification.valid else []


@dataclass
class GeometryPlacementResult:
    success: bool
    requested_quantity: int
    positions_m: list[tuple[float, float]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    wall_clearance_ok: bool = False
    spacing_ok: bool = False
    throw_t50_m: float | None = None


def place_diffusers_in_geometry(
        geometry: RoomGeometry, quantity: int,
        min_wall_clearance_m: float = 0.30,
        min_spacing_m: float = 0.0,
        throw_t50_m: float | None = None,
        face_half_extent_m: float = 0.0) -> GeometryPlacementResult:
    """Find a complete deterministic layout.

    Phase 5 integration
    -------------------
    * Primary path: `placement_engine_adapter.place_via_engine` (which
      calls `placement_engine.place_diffusers` with Tier A/B/C dispatch
      and the exact mathematical verifier).
    * Fallback: the legacy bounded-polygon grid algorithm — used ONLY
      when the engine returns a non-final verdict or raises.
    * FINAL engine verdicts (SUCCESS, CAPACITY_EXCEEDED) are returned
      directly; the legacy path is NOT consulted for them.
    """
    if (not math.isfinite(face_half_extent_m) or face_half_extent_m < 0):
        return GeometryPlacementResult(
            False, quantity,
            errors=["Diffuser face extent must be finite and non-negative."])
    center_clearance_m = min_wall_clearance_m + face_half_extent_m

    # --- Guard rails: mirror legacy semantics on trivial / invalid inputs ---
    if quantity <= 0:
        return _legacy_place_diffusers_in_geometry_impl(
            geometry, quantity, center_clearance_m, min_spacing_m,
            throw_t50_m)
    if (not math.isfinite(min_wall_clearance_m) or min_wall_clearance_m < 0
            or not math.isfinite(min_spacing_m) or min_spacing_m < 0):
        return _legacy_place_diffusers_in_geometry_impl(
            geometry, quantity, center_clearance_m, min_spacing_m,
            throw_t50_m)
    if (throw_t50_m is not None
            and (not math.isfinite(throw_t50_m) or throw_t50_m <= 0)):
        return _legacy_place_diffusers_in_geometry_impl(
            geometry, quantity, center_clearance_m, min_spacing_m,
            throw_t50_m)

    # --- Engine path ---
    try:
        from ductdx.difusores.adaptador_posicionamento import (
            is_engine_verdict_final,
            place_via_engine,
        )
        from ductdx.difusores.motor_posicionamento import PlacementStatus

        engine_result = place_via_engine(
            geometry, quantity,
            wall_clearance_m=center_clearance_m,
            min_spacing_m=min_spacing_m,
            throw_t50_m=throw_t50_m,
        )

        if is_engine_verdict_final(engine_result.status):
            errors: list[str] = []
            if engine_result.status != PlacementStatus.SUCCESS:
                errors.append(
                    str(engine_result.diagnostics.get(
                        "reason", "placement_engine_failure")))
            return GeometryPlacementResult(
                success=(engine_result.status == PlacementStatus.SUCCESS),
                requested_quantity=quantity,
                positions_m=[tuple(p) for p in engine_result.positions_m],
                errors=errors,
                wall_clearance_ok=engine_result.wall_clearance_verified,
                spacing_ok=engine_result.spacing_verified,
                throw_t50_m=throw_t50_m,
            )
        # Non-final verdict → fall through to legacy.
    except (ImportError, TypeError, ValueError, RuntimeError) as exc:
        message = (
            "placement_engine_adapter raised "
            f"{type(exc).__name__}: {exc}. Falling back to legacy placement.")
        logger.warning(message, exc_info=True)
        warnings.warn(message, RuntimeWarning, stacklevel=2)

    # --- Legacy fallback ---
    return _legacy_place_diffusers_in_geometry_impl(
        geometry, quantity, center_clearance_m, min_spacing_m,
        throw_t50_m)


def _legacy_place_diffusers_in_geometry_impl(
        geometry: RoomGeometry, quantity: int,
        min_wall_clearance_m: float = 0.30,
        min_spacing_m: float = 0.0,
        throw_t50_m: float | None = None) -> GeometryPlacementResult:
    """Find a complete deterministic layout using a bounded polygon grid."""
    if quantity <= 0:
        return GeometryPlacementResult(
            False, quantity, errors=["Requested diffuser quantity must be positive."])
    if (not math.isfinite(min_wall_clearance_m) or min_wall_clearance_m < 0
            or not math.isfinite(min_spacing_m) or min_spacing_m < 0):
        return GeometryPlacementResult(
            False, quantity,
            errors=["Wall clearance and diffuser spacing must be finite and non-negative."])
    if (throw_t50_m is not None
            and (not math.isfinite(throw_t50_m) or throw_t50_m <= 0)):
        return GeometryPlacementResult(
            False, quantity,
            errors=["Diffuser T50 throw must be finite and greater than zero."])
    geometry_errors = geometry.validate()
    if geometry_errors:
        return GeometryPlacementResult(
            False, quantity,
            errors=["Invalid room geometry: " + "; ".join(geometry_errors)])

    min_x, max_x, min_y, max_y = geometry.bounding_box
    width, depth = max_x - min_x, max_y - min_y
    corners = {
        (min_x, min_y), (max_x, min_y),
        (max_x, max_y), (min_x, max_y),
    }
    axis_aligned_rectangle = (
        len(geometry.vertices) == 4
        and all(any(math.dist(point, corner) <= 1e-8 for corner in corners)
                for point in geometry.vertices)
    )
    if axis_aligned_rectangle:
        room = RoomLayout.from_geometry(geometry)
        grid = best_grid(room, quantity)
        rectangle_positions = [
            (min_x + ft_to_m(grid.cell_w * (col + 0.5)),
             min_y + ft_to_m(grid.cell_l * (row + 0.5)))
            for row in range(grid.rows) for col in range(grid.cols)
        ]
        wall_ok = all(
            geometry.distance_to_walls(*point) + 1e-9 >= min_wall_clearance_m
            for point in rectangle_positions)
        spacing_ok = all(
            math.dist(rectangle_positions[i], rectangle_positions[j]) + 1e-9
            >= min_spacing_m
            for i in range(len(rectangle_positions))
            for j in range(i + 1, len(rectangle_positions)))
        if wall_ok and spacing_ok:
            return GeometryPlacementResult(
                True, quantity, positions_m=rectangle_positions,
                wall_clearance_ok=True, spacing_ok=True,
                throw_t50_m=throw_t50_m)

    divisions = max(15, min(60, math.ceil(max(width, depth) / 0.25)))
    candidates: list[tuple[float, float]] = []
    for row in range(divisions):
        y = min_y + (row + 0.5) * depth / divisions
        for col in range(divisions):
            x = min_x + (col + 0.5) * width / divisions
            if (geometry.contains_point(x, y)
                    and geometry.distance_to_walls(x, y) + 1e-9
                    >= min_wall_clearance_m):
                candidate = (round(x, 6), round(y, 6))
                if (geometry.contains_point(*candidate)
                        and geometry.distance_to_walls(*candidate) + 1e-9
                        >= min_wall_clearance_m):
                    candidates.append(candidate)

    if len(candidates) < quantity:
        return GeometryPlacementResult(
            False, quantity, errors=[
                (f"Geometry-infeasible: requested {quantity} diffusers, "
                f"but only {len(candidates)} valid candidate locations exist.")
            ])

    centroid = geometry.centroid
    chosen: list[tuple[float, float]] = []
    from ductdx.difusores.motor_posicionamento import (
        is_orthogonal_polygon,
        place_in_orthogonal_polygon,
        significant_subrectangle_count,
    )
    if is_orthogonal_polygon(geometry.vertices):
        wing_seed_count = min(
            quantity,
            significant_subrectangle_count(geometry.vertices,
                                           min_wall_clearance_m),
        )
        wing_seeds = place_in_orthogonal_polygon(
            geometry.vertices, wing_seed_count,
            wall_clearance_m=min_wall_clearance_m,
            min_spacing_m=min_spacing_m,
        )
        for point in wing_seeds:
            if (geometry.contains_point(*point)
                    and geometry.distance_to_walls(*point) + 1e-9
                    >= min_wall_clearance_m) and point not in candidates:
                candidates.append(point)
            if (point in candidates and all(
                    math.dist(point, placed) + 1e-9 >= min_spacing_m
                    for placed in chosen)):
                chosen.append(point)
    remaining = candidates
    while len(chosen) < quantity:
        eligible = [
            point for point in remaining
            if all(math.dist(point, placed) + 1e-9 >= min_spacing_m
                   for placed in chosen)
        ]
        if not eligible:
            return GeometryPlacementResult(
                False, quantity, errors=[
                    (f"Geometry-infeasible: requested {quantity} diffusers "
                    f"cannot satisfy {min_spacing_m:.3f} m minimum spacing.")
                ])
        if not chosen:
            point = min(eligible, key=lambda p: (
                math.dist(p, centroid), p[0], p[1]))
        else:
            point = max(eligible, key=lambda p: (
                min(math.dist(p, placed) for placed in chosen), -p[0], -p[1]))
        chosen.append(point)
        remaining.remove(point)

    wall_ok = all(
        geometry.contains_point(*point)
        and geometry.distance_to_walls(*point) + 1e-9 >= min_wall_clearance_m
        for point in chosen)
    spacing_ok = all(
        math.dist(chosen[i], chosen[j]) + 1e-9 >= min_spacing_m
        for i in range(len(chosen)) for j in range(i + 1, len(chosen)))
    if not wall_ok or not spacing_ok:
        return GeometryPlacementResult(
            False, quantity, errors=["Generated layout failed placement validation."])
    return GeometryPlacementResult(
        True, quantity, positions_m=chosen, wall_clearance_ok=wall_ok,
        spacing_ok=spacing_ok, throw_t50_m=throw_t50_m)

