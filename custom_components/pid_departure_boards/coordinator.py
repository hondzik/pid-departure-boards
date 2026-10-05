"""DataUpdateCoordinator — jeden na nástupiště (config subentry)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_LIMIT,
    CONF_ROUTES,
    CONF_SCAN_INTERVAL,
    CONF_STOP_ID,
    DEFAULT_LIMIT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    FETCH_LIMIT_FACTOR,
    MIN_FETCH_LIMIT,
    MINUTES_AFTER,
)
from .stops_cache import StopsCache
from .golemio_api import (
    GolemioAuthError,
    GolemioClient,
    GolemioError,
    GolemioRateLimitError,
)
from .models import Departure, Infotext, filter_departures, parse_departures, parse_infotexts

_LOGGER = logging.getLogger(__name__)


@dataclass
class PlatformData:
    """Výsledek jedné aktualizace."""

    departures: list[Departure] = field(default_factory=list)
    infotexts: list[Infotext] = field(default_factory=list)


async def async_fetch_platform(
    client: GolemioClient,
    stop_id: str,
    routes: set[str],
    limit: int,
) -> PlatformData:
    """Stáhne odjezdy a infotexty jednoho nástupiště (sdíleno službou `get_departures`)."""
    raw = await client.async_get_departures(
        [stop_id],
        minutes_after=MINUTES_AFTER,
        limit=max(limit * FETCH_LIMIT_FACTOR, MIN_FETCH_LIMIT),
    )
    departures = filter_departures(parse_departures(raw), routes, limit)
    infotexts = parse_infotexts(raw, {stop_id}, dt_util.utcnow())
    return PlatformData(departures, infotexts)


class PlatformCoordinator(DataUpdateCoordinator[PlatformData]):
    """Odjezdy z jednoho nástupiště."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
        client: GolemioClient,
        default_interval: int,
    ) -> None:
        interval = subentry.data.get(CONF_SCAN_INTERVAL) or default_interval
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {subentry.title}",
            update_interval=timedelta(seconds=interval or DEFAULT_SCAN_INTERVAL),
        )
        self._client = client
        self.subentry = subentry

    @property
    def stop_id(self) -> str:
        return self.subentry.data[CONF_STOP_ID]

    async def _async_update_data(self) -> PlatformData:
        data = self.subentry.data
        try:
            return await async_fetch_platform(
                self._client,
                self.stop_id,
                set(data.get(CONF_ROUTES) or []),
                int(data.get(CONF_LIMIT, DEFAULT_LIMIT)),
            )
        except GolemioAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except GolemioRateLimitError as err:
            raise UpdateFailed(f"Rate limit exceeded: {err}") from err
        except GolemioError as err:
            raise UpdateFailed(str(err)) from err


@dataclass
class PidRuntimeData:
    """Runtime data config entry (`entry.runtime_data`)."""

    client: GolemioClient
    stops_cache: StopsCache
    coordinators: dict[str, PlatformCoordinator] = field(default_factory=dict)


type PidConfigEntry = ConfigEntry[PidRuntimeData]
