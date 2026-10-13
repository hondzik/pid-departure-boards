"""Testy `vehicles.py` (cache pozic vozidel) — bez HA, importováno jako bare modul."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

INTEGRATION_DIR = (
    Path(__file__).resolve().parent.parent / "custom_components" / "pid_departure_boards"
)
sys.path.insert(0, str(INTEGRATION_DIR))
try:
    import vehicles
finally:
    sys.path.remove(str(INTEGRATION_DIR))

REAL = json.loads(
    (Path(__file__).parent / "fixtures" / "golemio_real" / "vehiclepositions.json").read_text("utf-8")
)


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def async_get_vehicle_positions(self, route: str):
        self.calls.append(route)
        await asyncio.sleep(0)  # dá šanci souběžným dotazům
        return REAL


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def make_cache(client, clock, ttl=5.0):
    return vehicles.VehiclePositionsCache(
        client, ttl=ttl, clock=clock, now=lambda: datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
    )


async def test_cached_within_ttl_and_refreshed_after():
    client, clock = FakeClient(), Clock()
    cache = make_cache(client, clock)

    first, fetched = await cache.async_get("20")
    assert len(first) == 2 and fetched.year == 2026
    clock.t = 4.9
    await cache.async_get("20")
    assert client.calls == ["20"]

    clock.t = 5.1
    await cache.async_get("20")
    assert client.calls == ["20", "20"]


async def test_routes_are_cached_separately():
    client, clock = FakeClient(), Clock()
    cache = make_cache(client, clock)
    await cache.async_get("20")
    await cache.async_get("12")
    assert client.calls == ["20", "12"]


async def test_concurrent_requests_share_one_call():
    client, clock = FakeClient(), Clock()
    cache = make_cache(client, clock)
    results = await asyncio.gather(*(cache.async_get("20") for _ in range(5)))
    assert client.calls == ["20"]
    assert all(r[0] == results[0][0] for r in results)
