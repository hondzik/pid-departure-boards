"""Cache seznamu zastávek (Store)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from custom_components.pid_departure_boards.golemio_api import GolemioClient
from custom_components.pid_departure_boards.stops_cache import StopsCache

from .conftest import API


def stops_calls(aioclient_mock) -> int:
    return len([c for c in aioclient_mock.mock_calls if "/v2/gtfs/stops" in str(c[1])])


@pytest.fixture
async def cache(hass: HomeAssistant, mock_api) -> StopsCache:
    return StopsCache(hass, GolemioClient(async_get_clientsession(hass), "k"))


async def test_downloads_once_and_reuses_memory(hass, mock_api, cache) -> None:
    index = await cache.async_get_index()
    assert index.search("palmovka") == ["Palmovka"]
    assert await cache.async_get_index() is index
    assert stops_calls(mock_api) == 1


async def test_fresh_store_is_reused_by_new_instance(hass, mock_api, cache) -> None:
    await cache.async_get_index()
    other = StopsCache(hass, GolemioClient(async_get_clientsession(hass), "k"))
    assert (await other.async_get_index()).search("anděl")
    assert stops_calls(mock_api) == 1  # druhá instance načetla uložená data


async def test_stale_store_is_refreshed(hass, mock_api, cache, hass_storage) -> None:
    await cache.async_get_index()
    old = (dt_util.utcnow() - timedelta(days=30)).isoformat()
    hass_storage["pid_departure_boards.stops"]["data"]["updated"] = old

    other = StopsCache(hass, GolemioClient(async_get_clientsession(hass), "k"))
    await other.async_get_index()
    assert stops_calls(mock_api) == 2


async def test_cache_without_coordinates_is_refetched(
    hass, mock_api, cache, hass_storage
) -> None:
    await cache.async_get_index()
    for stop in hass_storage["pid_departure_boards.stops"]["data"]["stops"]:
        del stop["lat"], stop["lon"]  # formát cache před přidáním souřadnic

    other = StopsCache(hass, GolemioClient(async_get_clientsession(hass), "k"))
    index = await other.async_get_index()
    assert stops_calls(mock_api) == 2
    assert index.coordinates("U1072Z101P") == (50.0716, 14.4036)


async def test_force_refresh(hass, mock_api, cache) -> None:
    await cache.async_get_index()
    await cache.async_get_index(force=True)
    assert stops_calls(mock_api) == 2
