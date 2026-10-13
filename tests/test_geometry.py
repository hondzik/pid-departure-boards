"""Testy `geometry.py` — bez HA, importováno jako bare modul."""

from __future__ import annotations

import json
import math
from pathlib import Path
import sys

INTEGRATION_DIR = (
    Path(__file__).resolve().parent.parent / "custom_components" / "pid_departure_boards"
)
sys.path.insert(0, str(INTEGRATION_DIR))
try:
    import geometry
finally:
    sys.path.remove(str(INTEGRATION_DIR))

REAL_SHAPE = [
    tuple(p)
    for p in json.loads(
        (Path(__file__).parent / "fixtures" / "golemio_real" / "shape_L20V2_coordinates.json").read_text(
            "utf-8"
        )
    )
]


def distance_to_polyline_m(point, polyline):
    """Nejmenší vzdálenost bodu od lomené čáry v metrech (lokální projekce)."""
    lat0 = math.radians(point[1])
    kx, ky = 111320 * math.cos(lat0), 110540

    def xy(p):
        return ((p[0] - point[0]) * kx, (p[1] - point[1]) * ky)

    best = math.inf
    for a, b in zip(polyline, polyline[1:]):
        best = min(best, geometry._distance_to_segment((0.0, 0.0), xy(a), xy(b)))
    return best


def test_short_input_is_returned_unchanged():
    assert geometry.simplify([], 5) == []
    assert geometry.simplify([(14.0, 50.0)], 5) == [(14.0, 50.0)]
    assert geometry.simplify([(14.0, 50.0), (14.1, 50.1)], 5) == [(14.0, 50.0), (14.1, 50.1)]


def test_non_positive_tolerance_keeps_everything():
    pts = [(14.0, 50.0), (14.0001, 50.0001), (14.0002, 50.0)]
    assert geometry.simplify(pts, 0) == pts


def test_collinear_points_are_dropped_but_ends_stay():
    pts = [(14.0 + i * 0.001, 50.0) for i in range(10)]
    assert geometry.simplify(pts, 5) == [pts[0], pts[-1]]


def test_corner_is_kept():
    # L: 1 km na východ, pak 1 km na sever; roh musí zůstat
    pts = [(14.0 + i * 0.0002, 50.0) for i in range(0, 8)]
    pts += [(pts[-1][0], 50.0 + j * 0.0002) for j in range(1, 8)]
    corner = (14.0 + 7 * 0.0002, 50.0)
    result = geometry.simplify(pts, 5)
    assert result == [pts[0], corner, pts[-1]]


def test_small_wiggle_below_tolerance_is_dropped_above_is_kept():
    # ~2 m a ~20 m odchylka od přímky
    small = [(14.0, 50.0), (14.0005, 50.00002), (14.001, 50.0)]
    big = [(14.0, 50.0), (14.0005, 50.0002), (14.001, 50.0)]
    assert len(geometry.simplify(small, 5)) == 2
    assert len(geometry.simplify(big, 5)) == 3


def test_order_is_preserved_and_result_is_subset():
    result = geometry.simplify(REAL_SHAPE, 5)
    positions = [REAL_SHAPE.index(p) for p in result]
    assert positions == sorted(positions)
    assert result[0] == REAL_SHAPE[0] and result[-1] == REAL_SHAPE[-1]


def test_real_route_stays_within_tolerance_and_shrinks():
    """Skutečná trasa tramvaje 20: žádný původní bod není dál než tolerance od výsledku."""
    for tolerance in (3, 5, 10):
        result = geometry.simplify(REAL_SHAPE, tolerance)
        worst = max(distance_to_polyline_m(p, result) for p in REAL_SHAPE)
        # drobná rezerva na rozdíl projekcí (celá trasa × lokální projekce bodu)
        assert worst <= tolerance * 1.05, (tolerance, worst)

    simplified = geometry.simplify(REAL_SHAPE, 5)
    assert len(REAL_SHAPE) == 430
    assert len(simplified) < len(REAL_SHAPE) * 0.25  # změřeno: ~17 %


def test_round_points():
    assert geometry.round_points([(14.4036312, 50.0719349)]) == [(14.40363, 50.07193)]
    assert geometry.round_points([(14.4036312, 50.0719349)], 3) == [(14.404, 50.072)]
