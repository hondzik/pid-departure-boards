"""Cache tras (`helpers.storage.Store`) — zjednodušené trasy podle `shape_id`."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    SHAPE_SIMPLIFY_TOLERANCE_M,
    SHAPES_MAX_AGE_DAYS,
    SHAPES_STORAGE_VERSION,
)
from .geometry import round_points, simplify
from .golemio_api import GolemioClient, GolemioConnectionError
from .models import RouteShape, TripInfo, parse_shape_points, parse_trip_info

SAVE_DELAY = 10  # s


class ShapesCache:
    """Trasa spoje: `trip_id` → `shape_id` (paměť) → zjednodušené body (paměť + Store, 7 dní).

    Stahuje se nejdřív malý záznam spoje (~0,3 kB) kvůli `shape_id`; samotná trasa (~74 kB)
    jen když ji cache nezná. Stažená trasa se zjednoduší (5 m) a zaokrouhlí, než se uloží.
    """

    def __init__(self, hass: HomeAssistant, client: GolemioClient) -> None:
        self._client = client
        self._store: Store = Store(hass, SHAPES_STORAGE_VERSION, f"{DOMAIN}.shapes")
        self._shapes: dict[str, dict[str, Any]] | None = None
        self._trips: dict[str, TripInfo] = {}
        self._lock = asyncio.Lock()

    async def _async_load(self) -> dict[str, dict[str, Any]]:
        if self._shapes is None:
            stored = await self._store.async_load() or {}
            limit = dt_util.utcnow() - timedelta(days=SHAPES_MAX_AGE_DAYS)
            self._shapes = {
                shape_id: item
                for shape_id, item in (stored.get("shapes") or {}).items()
                if (updated := dt_util.parse_datetime(item.get("updated", ""))) and updated > limit
            }
        return self._shapes

    async def async_get_route_shape(self, trip_id: str) -> RouteShape:
        """Zjednodušená trasa spoje; chyby API se propagují jako `GolemioError`."""
        async with self._lock:
            shapes = await self._async_load()

            trip = self._trips.get(trip_id)
            if trip is None:
                trip = parse_trip_info(await self._client.async_get_trip(trip_id))
                if trip is None or not trip.shape_id:
                    raise GolemioConnectionError(f"trip {trip_id} has no shape")
                self._trips[trip_id] = trip

            item = shapes.get(trip.shape_id)
            if item is None:
                points = parse_shape_points(await self._client.async_get_shape(trip.shape_id))
                if len(points) < 2:
                    raise GolemioConnectionError(f"shape {trip.shape_id} is empty")
                simplified = round_points(simplify(points, SHAPE_SIMPLIFY_TOLERANCE_M))
                item = {
                    "updated": dt_util.utcnow().isoformat(),
                    "coordinates": [[lon, lat] for lon, lat in simplified],
                }
                shapes[trip.shape_id] = item
                self._store.async_delay_save(lambda: {"shapes": shapes}, SAVE_DELAY)

            return RouteShape(
                shape_id=trip.shape_id,
                headsign=trip.headsign,
                direction_id=trip.direction_id,
                coordinates=item["coordinates"],
            )
