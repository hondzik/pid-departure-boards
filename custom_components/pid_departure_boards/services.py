"""Služby `refresh` a `get_departures`."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_LIMIT,
    CONF_ROUTES,
    DEFAULT_LIMIT,
    DOMAIN,
    MAX_LIMIT,
    SERVICE_GET_DEPARTURES,
    SERVICE_REFRESH,
)
from .coordinator import PidConfigEntry, PlatformCoordinator, async_fetch_platform
from .golemio_api import GolemioError

ATTR_ENTITY_ID = "entity_id"
ATTR_STOP_ID = "stop_id"
ATTR_CONFIG_ENTRY_ID = "config_entry_id"

REFRESH_SCHEMA = vol.Schema({vol.Optional(ATTR_ENTITY_ID): cv.entity_ids})

GET_DEPARTURES_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTITY_ID): cv.entity_id,
        vol.Optional(ATTR_STOP_ID): cv.string,
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(CONF_ROUTES): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(CONF_LIMIT): vol.All(vol.Coerce(int), vol.Range(min=1, max=MAX_LIMIT)),
    }
)


def _loaded_entries(hass: HomeAssistant) -> list[PidConfigEntry]:
    return hass.config_entries.async_loaded_entries(DOMAIN)


def _coordinator_for_entity(hass: HomeAssistant, entity_id: str) -> PlatformCoordinator:
    reg_entry = er.async_get(hass).async_get(entity_id)
    if reg_entry is None or reg_entry.platform != DOMAIN:
        raise ServiceValidationError(f"{entity_id} is not a {DOMAIN} entity")
    for entry in _loaded_entries(hass):
        if entry.entry_id == reg_entry.config_entry_id:
            coordinator = entry.runtime_data.coordinators.get(reg_entry.config_subentry_id)
            if coordinator:
                return coordinator
    raise ServiceValidationError(f"{entity_id} is not loaded")


def async_setup_services(hass: HomeAssistant) -> None:
    async def handle_refresh(call: ServiceCall) -> None:
        entity_ids = call.data.get(ATTR_ENTITY_ID)
        if entity_ids:
            coordinators = [_coordinator_for_entity(hass, e) for e in entity_ids]
        else:
            coordinators = [
                c for entry in _loaded_entries(hass) for c in entry.runtime_data.coordinators.values()
            ]
        for coordinator in coordinators:
            await coordinator.async_request_refresh()

    async def handle_get_departures(call: ServiceCall) -> dict[str, Any]:
        data = call.data
        entity_id = data.get(ATTR_ENTITY_ID)
        stop_id = data.get(ATTR_STOP_ID)
        if bool(entity_id) == bool(stop_id):
            raise ServiceValidationError("Provide exactly one of entity_id or stop_id")

        if entity_id:
            coordinator = _coordinator_for_entity(hass, entity_id)
            client = coordinator.config_entry.runtime_data.client
            stop_id = coordinator.stop_id
            default_routes = coordinator.subentry.data.get(CONF_ROUTES) or []
            default_limit = coordinator.subentry.data.get(CONF_LIMIT, DEFAULT_LIMIT)
        else:
            entries = _loaded_entries(hass)
            if cid := data.get(ATTR_CONFIG_ENTRY_ID):
                entries = [e for e in entries if e.entry_id == cid]
            if not entries:
                raise ServiceValidationError("No loaded PID Departure Boards entry found")
            client = entries[0].runtime_data.client
            default_routes, default_limit = [], DEFAULT_LIMIT

        routes = set(data.get(CONF_ROUTES, default_routes))
        limit = data.get(CONF_LIMIT, default_limit)
        try:
            result = await async_fetch_platform(client, stop_id, routes, limit)
        except GolemioError as err:
            raise HomeAssistantError(f"Golemio API error: {err}") from err

        language = hass.config.language
        return {
            "stop_id": stop_id,
            "departures": [d.as_dict() for d in result.departures],
            "infotexts": [i.as_dict(language) for i in result.infotexts],
        }

    hass.services.async_register(DOMAIN, SERVICE_REFRESH, handle_refresh, schema=REFRESH_SCHEMA)
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_DEPARTURES,
        handle_get_departures,
        schema=GET_DEPARTURES_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
