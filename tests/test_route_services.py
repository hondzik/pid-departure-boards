"""Služby `get_route_shapes` a `get_vehicle_positions`, cache tras a `route_trips`."""

from __future__ import annotations

from datetime import timedelta

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from custom_components.pid_departure_boards.const import DOMAIN
from custom_components.pid_departure_boards.golemio_api import GolemioClient
from custom_components.pid_departure_boards.shapes_cache import ShapesCache

from .conftest import API
from .test_init import NOW, make_entry, setup

# linka → (trip_id v ukázkové tabuli, shape_id, cíl)
TRIPS = {
    "5": ("5_1234_260101", "S5", "Sidliste Barrandov"),
    "12": ("12_77_260101", "S12", "Pohorelec"),
    "N91": ("N91_5_260101", "SN91", "Cerny Most"),
}


def straight_shape(shape_id: str) -> dict:
    """100 bodů na přímce na východ + 100 bodů na sever (roh); po zjednodušení zbudou 3."""
    coords = [(14.0 + i * 0.0001, 50.0) for i in range(100)]
    coords += [(coords[-1][0], 50.0 + j * 0.0001) for j in range(1, 101)]
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": list(c)},
                "properties": {"shape_id": shape_id, "shape_pt_sequence": i + 1},
            }
            for i, c in enumerate(coords)
        ],
    }


def vehicle(route: str, headsign: str, trip_id: str, lon: float, lat: float, delay_s=60) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "last_position": {
                "bearing": 90,
                "delay": {"actual": delay_s},
                "state_position": "on_track",
                "is_canceled": None,
            },
            "trip": {
                "gtfs": {
                    "route_short_name": route,
                    "trip_id": trip_id,
                    "trip_headsign": headsign,
                },
                "vehicle_registration_number": 8000 + int(lon * 100) % 100,
            },
        },
    }


@pytest.fixture
def mock_route_api(mock_api):
    for route, (trip_id, shape_id, headsign) in TRIPS.items():
        mock_api.get(
            f"{API}/v2/gtfs/trips/{trip_id}",
            json={
                "trip_id": trip_id,
                "shape_id": shape_id,
                "direction_id": 0,
                "trip_headsign": headsign,
            },
        )
        mock_api.get(f"{API}/v2/gtfs/shapes/{shape_id}", json=straight_shape(shape_id))
    mock_api.get(
        f"{API}/v2/vehiclepositions?routeShortName=5",
        json={
            "type": "FeatureCollection",
            "features": [
                vehicle("5", "Sidliste Barrandov", "5_1_x", 14.40, 50.07),
                vehicle("5", "Hostivar", "5_2_x", 14.41, 50.08),  # opačný směr
            ],
        },
    )
    return mock_api


def calls(mock, fragment: str) -> int:
    return len([c for c in mock.mock_calls if fragment in str(c[1])])


async def call(hass: HomeAssistant, service: str, data: dict) -> dict:
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=True
    )


# ---- route_trips v coordinatoru ----


async def test_route_trips_are_computed_before_limit_and_for_selected_routes(
    hass: HomeAssistant, mock_route_api, freezer
) -> None:
    freezer.move_to(NOW)
    entry = make_entry(routes=["5", "N91"], limit=1)
    await setup(hass, entry)

    (coordinator,) = entry.runtime_data.coordinators.values()
    assert [d.route for d in coordinator.data.departures] == ["5"]  # limit 1
    assert coordinator.data.route_trips == {
        "5": ("5_1234_260101", "Sidliste Barrandov"),
        "N91": ("N91_5_260101", "Cerny Most"),  # nevešla se do limitu, přesto je referenční
    }


async def test_route_trips_all_routes_when_none_selected(
    hass: HomeAssistant, mock_route_api, freezer
) -> None:
    freezer.move_to(NOW)
    entry = make_entry()
    await setup(hass, entry)
    (coordinator,) = entry.runtime_data.coordinators.values()
    assert set(coordinator.data.route_trips) == {"5", "12", "N91"}


# ---- get_route_shapes ----


async def test_get_route_shapes_returns_simplified_lon_lat(
    hass: HomeAssistant, mock_route_api, freezer
) -> None:
    freezer.move_to(NOW)
    await setup(hass, make_entry())

    result = await call(hass, "get_route_shapes", {"entity_id": "sensor.andel_b"})

    assert result["stop_id"] == "U1072Z101P"
    assert [r["route"] for r in result["routes"]] == ["5", "12", "N91"]  # číselné, pak N91
    five = result["routes"][0]
    assert (five["shape_id"], five["headsign"]) == ("S5", "Sidliste Barrandov")
    # 200 bodů → začátek, roh, konec; souřadnice [lon, lat] zaokrouhlené na 5 míst
    assert five["coordinates"] == [[14.0, 50.0], [14.0099, 50.0], [14.0099, 50.01]]


async def test_get_route_shapes_downloads_each_shape_once(
    hass: HomeAssistant, mock_route_api, freezer
) -> None:
    freezer.move_to(NOW)
    await setup(hass, make_entry())

    await call(hass, "get_route_shapes", {"entity_id": "sensor.andel_b"})
    assert calls(mock_route_api, "/v2/gtfs/trips/") == 3
    assert calls(mock_route_api, "/v2/gtfs/shapes/") == 3

    await call(hass, "get_route_shapes", {"entity_id": "sensor.andel_b"})
    assert calls(mock_route_api, "/v2/gtfs/trips/") == 3  # ani spoj, ani trasu už nestahuje
    assert calls(mock_route_api, "/v2/gtfs/shapes/") == 3


async def test_get_route_shapes_route_without_reference_trip(
    hass: HomeAssistant, mock_route_api, freezer
) -> None:
    freezer.move_to(NOW)
    await setup(hass, make_entry(routes=["5", "99"]))  # 99 v odjezdech není

    result = await call(hass, "get_route_shapes", {"entity_id": "sensor.andel_b"})
    by_route = {r["route"]: r for r in result["routes"]}
    assert by_route["99"] == {"route": "99", "headsign": None, "shape_id": None, "coordinates": None}
    assert by_route["5"]["coordinates"]


async def test_get_route_shapes_api_error(hass: HomeAssistant, mock_api, freezer) -> None:
    freezer.move_to(NOW)
    mock_api.get(f"{API}/v2/gtfs/trips/5_1234_260101", status=500)
    await setup(hass, make_entry(routes=["5"]))

    with pytest.raises(HomeAssistantError):
        await call(hass, "get_route_shapes", {"entity_id": "sensor.andel_b"})


# ---- get_vehicle_positions ----


async def test_get_vehicle_positions_keeps_only_our_direction(
    hass: HomeAssistant, mock_route_api, freezer
) -> None:
    freezer.move_to(NOW)
    await setup(hass, make_entry(routes=["5"]))

    result = await call(hass, "get_vehicle_positions", {"entity_id": "sensor.andel_b"})

    assert result["stop_id"] == "U1072Z101P"
    assert result["routes_without_reference"] == []
    assert result["updated"]
    (veh,) = result["vehicles"]
    assert veh["headsign"] == "Sidliste Barrandov"
    assert (veh["longitude"], veh["latitude"]) == (14.40, 50.07)
    assert veh["delay_min"] == 1 and veh["bearing"] == 90 and veh["state"] == "on_track"


async def test_get_vehicle_positions_without_reference_trip_skips_route(
    hass: HomeAssistant, mock_route_api, freezer
) -> None:
    freezer.move_to(NOW)
    await setup(hass, make_entry(routes=["5", "99"]))

    result = await call(hass, "get_vehicle_positions", {"entity_id": "sensor.andel_b"})
    assert result["routes_without_reference"] == ["99"]
    assert len(result["vehicles"]) == 1
    assert calls(mock_route_api, "routeShortName=99") == 0  # bez směru se ani nevolá


async def test_get_vehicle_positions_are_cached_briefly(
    hass: HomeAssistant, mock_route_api, freezer
) -> None:
    freezer.move_to(NOW)
    await setup(hass, make_entry(routes=["5"]))

    await call(hass, "get_vehicle_positions", {"entity_id": "sensor.andel_b"})
    await call(hass, "get_vehicle_positions", {"entity_id": "sensor.andel_b"})
    assert calls(mock_route_api, "/v2/vehiclepositions") == 1


async def test_get_vehicle_positions_api_error(hass: HomeAssistant, mock_api, freezer) -> None:
    freezer.move_to(NOW)
    mock_api.get(f"{API}/v2/vehiclepositions", status=500)
    await setup(hass, make_entry(routes=["5"]))

    with pytest.raises(HomeAssistantError):
        await call(hass, "get_vehicle_positions", {"entity_id": "sensor.andel_b"})


@pytest.mark.parametrize("service", ["get_route_shapes", "get_vehicle_positions"])
async def test_services_reject_foreign_entity(
    hass: HomeAssistant, mock_route_api, freezer, service
) -> None:
    freezer.move_to(NOW)
    await setup(hass, make_entry())
    hass.states.async_set("sensor.other", "1")

    with pytest.raises(ServiceValidationError):
        await call(hass, service, {"entity_id": "sensor.other"})


# ---- cache tras ----


@pytest.fixture
async def shapes_cache(hass: HomeAssistant, mock_route_api) -> ShapesCache:
    return ShapesCache(hass, GolemioClient(async_get_clientsession(hass), "k"))


async def test_shapes_cache_persists_between_instances(
    hass: HomeAssistant, mock_route_api, shapes_cache, hass_storage
) -> None:
    shape = await shapes_cache.async_get_route_shape("5_1234_260101")
    assert shape.shape_id == "S5" and shape.direction_id == 0
    await hass.async_block_till_done(wait_background_tasks=True)
    # uložení je odložené (async_delay_save) — vynutíme zápis
    await shapes_cache._store.async_save({"shapes": shapes_cache._shapes})
    assert "S5" in hass_storage["pid_departure_boards.shapes"]["data"]["shapes"]

    other = ShapesCache(hass, GolemioClient(async_get_clientsession(hass), "k"))
    again = await other.async_get_route_shape("5_1234_260101")
    assert again.coordinates == shape.coordinates
    assert calls(mock_route_api, "/v2/gtfs/shapes/") == 1  # trasu druhá instance načetla z úložiště
    assert calls(mock_route_api, "/v2/gtfs/trips/") == 2  # spoj (0,3 kB) se zjišťuje znovu


async def test_shapes_cache_drops_expired_entries(
    hass: HomeAssistant, mock_route_api, shapes_cache, hass_storage
) -> None:
    await shapes_cache.async_get_route_shape("5_1234_260101")
    await shapes_cache._store.async_save({"shapes": shapes_cache._shapes})
    old = (dt_util.utcnow() - timedelta(days=30)).isoformat()
    hass_storage["pid_departure_boards.shapes"]["data"]["shapes"]["S5"]["updated"] = old

    other = ShapesCache(hass, GolemioClient(async_get_clientsession(hass), "k"))
    await other.async_get_route_shape("5_1234_260101")
    assert calls(mock_route_api, "/v2/gtfs/shapes/") == 2  # prošlá trasa se stáhla znovu
