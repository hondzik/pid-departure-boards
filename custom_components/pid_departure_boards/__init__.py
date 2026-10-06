"""PID Departure Boards — odjezdové tabule PID (Golemio API)."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_API_KEY,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SUBENTRY_TYPE_STOP,
)
from .coordinator import PidConfigEntry, PidRuntimeData, PlatformCoordinator
from .golemio_api import GolemioClient
from .services import async_setup_services
from .stops_cache import StopsCache

PLATFORMS = [Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Služby se registrují jednou, ne per config entry."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: PidConfigEntry) -> bool:
    client = GolemioClient(async_get_clientsession(hass), entry.data[CONF_API_KEY])
    default_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

    runtime = PidRuntimeData(client=client, stops_cache=StopsCache(hass, client))
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_STOP:
            continue
        coordinator = PlatformCoordinator(hass, entry, subentry, client, default_interval)
        await coordinator.async_config_entry_first_refresh()
        runtime.coordinators[subentry.subentry_id] = coordinator
    entry.runtime_data = runtime

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_on_update))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PidConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_on_update(hass: HomeAssistant, entry: PidConfigEntry) -> None:
    """Změna options nebo subentries (přidání/úprava/odebrání nástupiště)."""
    await hass.config_entries.async_reload(entry.entry_id)
