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
    SERVICE_GET_ROUTE_SHAPES,
    SERVICE_GET_VEHICLE_POSITIONS,
    SERVICE_REFRESH,
)
from .coordinator import PidConfigEntry, PlatformCoordinator, async_fetch_platform
from .golemio_api import GolemioError
from .models import filter_vehicles, route_sort_key

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


ENTITY_SCHEMA = vol.Schema({vol.Required(ATTR_ENTITY_ID): cv.entity_id})


def _sorted_routes(coordinator: PlatformCoordinator) -> list[str]:
    """Sledované linky nástupiště; prázdný výběr v konfiguraci = všechny linky z odjezdů."""
    selected = coordinator.subentry.data.get(CONF_ROUTES) or list(coordinator.data.route_trips)
    return sorted(selected, key=route_sort_key)


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

    async def handle_get_route_shapes(call: ServiceCall) -> dict[str, Any]:
        coordinator = _coordinator_for_entity(hass, call.data[ATTR_ENTITY_ID])
        shapes_cache = coordinator.config_entry.runtime_data.shapes_cache
        routes = []
        for route in _sorted_routes(coordinator):
            reference = coordinator.data.route_trips.get(route)
            if reference is None:  # linka bez odjezdu v okně → neznáme spoj, ani trasu
                routes.append(
                    {"route": route, "headsign": None, "shape_id": None, "coordinates": None}
                )
                continue
            trip_id, headsign = reference
            try:
                shape = await shapes_cache.async_get_route_shape(trip_id)
            except GolemioError as err:
                raise HomeAssistantError(f"Golemio API error: {err}") from err
            routes.append(
                {
                    "route": route,
                    "headsign": shape.headsign or headsign,
                    "shape_id": shape.shape_id,
                    "coordinates": shape.coordinates,
                }
            )
        return {"stop_id": coordinator.stop_id, "routes": routes}

    async def handle_get_vehicle_positions(call: ServiceCall) -> dict[str, Any]:
        coordinator = _coordinator_for_entity(hass, call.data[ATTR_ENTITY_ID])
        vehicles_cache = coordinator.config_entry.runtime_data.vehicles_cache
        vehicles: list[dict[str, Any]] = []
        without_reference: list[str] = []
        fetched_times = []
        for route in _sorted_routes(coordinator):
            reference = coordinator.data.route_trips.get(route)
            if reference is None or reference[1] is None:
                # bez referenčního spoje neznáme směr → vozidla neukazujeme
                without_reference.append(route)
                continue
            try:
                route_vehicles, fetched = await vehicles_cache.async_get(route)
            except GolemioError as err:
                raise HomeAssistantError(f"Golemio API error: {err}") from err
            fetched_times.append(fetched)
            vehicles += [
                v.as_dict() for v in filter_vehicles(route_vehicles, route, reference[1])
            ]
        return {
            "stop_id": coordinator.stop_id,
            "updated": min(fetched_times).isoformat() if fetched_times else None,
            "vehicles": vehicles,
            "routes_without_reference": without_reference,
        }

    hass.services.async_register(DOMAIN, SERVICE_REFRESH, handle_refresh, schema=REFRESH_SCHEMA)
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_ROUTE_SHAPES,
        handle_get_route_shapes,
        schema=ENTITY_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_VEHICLE_POSITIONS,
        handle_get_vehicle_positions,
        schema=ENTITY_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_DEPARTURES,
        handle_get_departures,
        schema=GET_DEPARTURES_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
