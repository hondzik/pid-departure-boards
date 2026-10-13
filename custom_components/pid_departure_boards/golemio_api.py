"""Async klient Golemio PID API. Bez importu homeassistant.*."""

from __future__ import annotations

import asyncio
from collections import deque
import time
from collections.abc import Callable
from typing import Any

import aiohttp

try:
    from .const import (
        API_BASE_URL,
        RATE_LIMIT_CALLS,
        RATE_LIMIT_MAX_WAIT,
        RATE_LIMIT_PERIOD,
    )
except ImportError:  # bare-module import v testech
    from const import (
        API_BASE_URL,
        RATE_LIMIT_CALLS,
        RATE_LIMIT_MAX_WAIT,
        RATE_LIMIT_PERIOD,
    )

REQUEST_TIMEOUT = 15
STOPS_PAGE_SIZE = 10000


class GolemioError(Exception):
    """Obecná chyba klienta."""


class GolemioAuthError(GolemioError):
    """Neplatný nebo chybějící API klíč (401/403)."""


class GolemioRateLimitError(GolemioError):
    """Překročen rate limit (429)."""


class GolemioConnectionError(GolemioError):
    """Síťová chyba, chyba serveru nebo nevalidní odpověď."""


class RateLimiter:
    """Klouzavé okno: nejvýš `max_calls` požadavků za `period` sekund.

    API rate limit v odpovědích neoznamuje, proto se hlídá na straně klienta. Čeká se
    nejvýš `max_wait` sekund, jinak `GolemioRateLimitError` (mapa nesmí vyhladovět obnovu odjezdů).
    """

    def __init__(
        self,
        max_calls: int = RATE_LIMIT_CALLS,
        period: float = RATE_LIMIT_PERIOD,
        max_wait: float = RATE_LIMIT_MAX_WAIT,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_calls = max_calls
        self._period = period
        self._max_wait = max_wait
        self._clock = clock
        self._calls: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = self._clock()
            while self._calls and now - self._calls[0] >= self._period:
                self._calls.popleft()
            if len(self._calls) >= self._max_calls:
                wait = self._calls[0] + self._period - now
                if wait > self._max_wait:
                    raise GolemioRateLimitError("client-side rate limit")
                await asyncio.sleep(wait)
                self._calls.popleft()  # nejstarší volání po čekání vypadlo z okna
                now = self._clock()
            self._calls.append(now)


class GolemioClient:
    """Tenký klient nad aiohttp session."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        base_url: str = API_BASE_URL,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self._session = session
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._rate_limiter = rate_limiter or RateLimiter()

    async def _get(self, path: str, params: list[tuple[str, str]]) -> Any:
        await self._rate_limiter.acquire()
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.get(
                    f"{self._base_url}{path}",
                    params=params,
                    headers={"X-Access-Token": self._api_key},
                ) as resp:
                    if resp.status in (401, 403):
                        raise GolemioAuthError(f"HTTP {resp.status}")
                    if resp.status == 429:
                        raise GolemioRateLimitError("HTTP 429")
                    if resp.status >= 400:
                        raise GolemioConnectionError(f"HTTP {resp.status}")
                    return await resp.json(content_type=None)
        except GolemioError:
            raise
        except TimeoutError as err:
            raise GolemioConnectionError("timeout") from err
        except (aiohttp.ClientError, ValueError) as err:
            raise GolemioConnectionError(str(err)) from err

    async def async_get_departures(
        self,
        stop_ids: list[str],
        *,
        minutes_after: int,
        limit: int,
        route_filter: str | None = None,
    ) -> dict[str, Any]:
        """`GET /v2/pid/departureboards` — surová odpověď (`departures`, `stops`, `infotexts`)."""
        params: list[tuple[str, str]] = [("ids[]", s) for s in stop_ids]
        params += [
            ("minutesAfter", str(minutes_after)),
            ("limit", str(limit)),
            ("order", "real"),
        ]
        if route_filter:
            params.append(("filter", route_filter))
        data = await self._get("/v2/pid/departureboards", params)
        if not isinstance(data, dict):
            raise GolemioConnectionError("unexpected response")
        return data

    async def async_get_trip(self, trip_id: str) -> dict[str, Any]:
        """`GET /v2/gtfs/trips/{id}` bez tras (~0,3 kB): `shape_id`, `direction_id`, `trip_headsign`."""
        data = await self._get(f"/v2/gtfs/trips/{trip_id}", [])
        if not isinstance(data, dict):
            raise GolemioConnectionError("unexpected response")
        return data

    async def async_get_shape(self, shape_id: str) -> dict[str, Any]:
        """`GET /v2/gtfs/shapes/{id}` — `FeatureCollection` bodů trasy."""
        data = await self._get(f"/v2/gtfs/shapes/{shape_id}", [])
        if not isinstance(data, dict):
            raise GolemioConnectionError("unexpected response")
        return data

    async def async_get_vehicle_positions(self, route_short_name: str) -> dict[str, Any]:
        """`GET /v2/vehiclepositions` — pozice vozidel jedné linky (`FeatureCollection`)."""
        data = await self._get(
            "/v2/vehiclepositions",
            [("routeShortName", route_short_name), ("limit", "200")],
        )
        if not isinstance(data, dict):
            raise GolemioConnectionError("unexpected response")
        return data

    async def async_validate(self) -> None:
        """Ověří API klíč levným dotazem (jedna zastávka)."""
        await self._get("/v2/gtfs/stops", [("limit", "1")])

    async def async_get_stops(self) -> list[dict[str, Any]]:
        """Všechny zastávky z `/v2/gtfs/stops` (stránkováno), jako seznam `properties`."""
        stops: list[dict[str, Any]] = []
        offset = 0
        while True:
            data = await self._get(
                "/v2/gtfs/stops",
                [("limit", str(STOPS_PAGE_SIZE)), ("offset", str(offset))],
            )
            features = data.get("features") if isinstance(data, dict) else None
            if features is None:
                raise GolemioConnectionError("unexpected response")
            for feature in features:
                if "properties" not in feature:
                    continue
                props = dict(feature["properties"])
                coords = (feature.get("geometry") or {}).get("coordinates")
                if isinstance(coords, list) and len(coords) >= 2:
                    props["stop_lon"], props["stop_lat"] = coords[0], coords[1]  # GeoJSON: lon, lat
                stops.append(props)
            if len(features) < STOPS_PAGE_SIZE:
                return stops
            offset += STOPS_PAGE_SIZE
