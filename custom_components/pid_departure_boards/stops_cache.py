"""Perzistentní cache seznamu zastávek (`helpers.storage.Store`)."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN, STOPS_MAX_AGE_DAYS, STOPS_STORAGE_VERSION
from .golemio_api import GolemioClient
from .stops import StopIndex, slim_stops


class StopsCache:
    """Stahuje seznam zastávek jednou za týden a drží ho v paměti jako `StopIndex`."""

    def __init__(self, hass: HomeAssistant, client: GolemioClient) -> None:
        self._client = client
        self._store: Store = Store(hass, STOPS_STORAGE_VERSION, f"{DOMAIN}.stops")
        self._index: StopIndex | None = None

    async def async_get_index(self, *, force: bool = False) -> StopIndex:
        if self._index is not None and not force:
            return self._index

        stored = await self._store.async_load()
        if stored and not force:
            updated = dt_util.parse_datetime(stored.get("updated", ""))
            fresh = updated and dt_util.utcnow() - updated < timedelta(days=STOPS_MAX_AGE_DAYS)
            if fresh and stored.get("stops"):
                self._index = StopIndex(stored["stops"])
                return self._index

        stops = slim_stops(await self._client.async_get_stops())
        await self._store.async_save(
            {"updated": _now_iso(), "stops": stops}
        )
        self._index = StopIndex(stops)
        return self._index


def _now_iso() -> str:
    now: datetime = dt_util.utcnow()
    return now.isoformat()
