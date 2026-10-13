"""Cache pozic vozidel s krátkou platností. Bez importu homeassistant.*."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone
import time

try:
    from .const import VEHICLES_CACHE_TTL
    from .golemio_api import GolemioClient
    from .models import Vehicle, parse_vehicles
except ImportError:  # bare-module import v testech
    from const import VEHICLES_CACHE_TTL
    from golemio_api import GolemioClient
    from models import Vehicle, parse_vehicles


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class VehiclePositionsCache:
    """Pozice vozidel podle linky, sdílené mezi všemi diváky.

    API cachuje odpověď ~5 s, takže častější dotazy nic nepřinesou. Souběžné dotazy na
    stejnou linku (víc karet, víc zařízení) se slučují do jednoho volání.
    """

    def __init__(
        self,
        client: GolemioClient,
        ttl: float = VEHICLES_CACHE_TTL,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._client = client
        self._ttl = ttl
        self._clock = clock
        self._now = now
        self._entries: dict[str, tuple[float, datetime, list[Vehicle]]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def async_get(self, route: str) -> tuple[list[Vehicle], datetime]:
        """Vozidla linky a čas jejich stažení."""
        lock = self._locks.setdefault(route, asyncio.Lock())
        async with lock:
            entry = self._entries.get(route)
            if entry and self._clock() - entry[0] < self._ttl:
                return entry[2], entry[1]
            vehicles = parse_vehicles(await self._client.async_get_vehicle_positions(route))
            fetched = self._now()
            self._entries[route] = (self._clock(), fetched, vehicles)
            return vehicles, fetched
