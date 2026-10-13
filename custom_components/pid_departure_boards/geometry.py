"""Zjednodušení trasy (Ramer–Douglas–Peucker). Bez importu homeassistant.*."""

from __future__ import annotations

import math
from collections.abc import Sequence

Point = tuple[float, float]  # (lon, lat)

_METERS_PER_DEG_LAT = 110540.0
_METERS_PER_DEG_LON_EQUATOR = 111320.0


def _project(points: Sequence[Point]) -> list[tuple[float, float]]:
    """Lokální rovinná projekce (metry) kolem průměrné šířky — pro město stačí."""
    lat0 = math.radians(sum(lat for _, lat in points) / len(points))
    kx = _METERS_PER_DEG_LON_EQUATOR * math.cos(lat0)
    lon0, lat_first = points[0]
    return [((lon - lon0) * kx, (lat - lat_first) * _METERS_PER_DEG_LAT) for lon, lat in points]


def _distance_to_segment(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(p[0] - ax, p[1] - ay)
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def simplify(points: Sequence[Point], tolerance_m: float) -> list[Point]:
    """Vyhodí body, které leží blíž než `tolerance_m` metrů od zjednodušené čáry.

    První a poslední bod zůstávají vždy; pořadí se zachovává. Žádný původní bod není
    po zjednodušení dál než `tolerance_m` od výsledné čáry.
    """
    if len(points) <= 2 or tolerance_m <= 0:
        return list(points)

    xy = _project(points)
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        farthest, index = 0.0, None
        for i in range(first + 1, last):
            d = _distance_to_segment(xy[i], xy[first], xy[last])
            if d > farthest:
                farthest, index = d, i
        if index is not None and farthest > tolerance_m:
            keep[index] = True
            stack.append((first, index))
            stack.append((index, last))
    return [p for p, k in zip(points, keep, strict=True) if k]


def round_points(points: Sequence[Point], digits: int = 5) -> list[Point]:
    """Zaokrouhlení souřadnic (5 desetinných míst ≈ 1 m)."""
    return [(round(lon, digits), round(lat, digits)) for lon, lat in points]
