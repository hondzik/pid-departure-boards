"""Setup integrace, sensor a služby."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import ConfigEntryState, ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from custom_components.pid_departure_boards.const import DOMAIN

from .conftest import API

STOP_ID = "U1072Z101P"
NOW = "2026-10-05T10:00:00+00:00"


def make_entry(routes=None, limit=5, **extra) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="PID Departure Boards",
        data={"api_key": "secret"},
        unique_id="abc",
        subentries_data=[
            ConfigSubentryData(
                data={
                    "stop_id": STOP_ID,
                    "stop_name": "Anděl",
                    "platform": "B",
                    "routes": routes or [],
                    "limit": limit,
                    **extra,
                },
                subentry_type="stop",
                title="Anděl B",
                unique_id=STOP_ID,
            )
        ],
    )


async def setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.usefixtures("mock_api")
async def test_sensor_state_and_attributes(hass: HomeAssistant, freezer) -> None:
    freezer.move_to(NOW)
    await setup(hass, make_entry())

    state = hass.states.get("sensor.andel_b")
    assert state is not None
    # nejbližší je linka 12 (10:02, bez predikce)
    assert state.state == "2026-10-05T10:02:00+00:00"
    assert state.attributes["stop_id"] == STOP_ID
    assert state.attributes["platform"] == "B"
    assert [d["route"] for d in state.attributes["departures"]] == ["12", "5", "N91"]
    # jazyk `hass` v testech je en → anglická verze, pokud existuje
    assert [i["text"] for i in state.attributes["infotexts"]] == [
        "Tram 5 diversion",
        "Obecny text",
    ]


@pytest.mark.usefixtures("mock_api")
async def test_route_filter_and_limit(hass: HomeAssistant, freezer) -> None:
    freezer.move_to(NOW)
    await setup(hass, make_entry(routes=["5", "N91"], limit=1))

    state = hass.states.get("sensor.andel_b")
    assert [d["route"] for d in state.attributes["departures"]] == ["5"]


async def test_request_uses_token_and_stop(hass: HomeAssistant, mock_api, freezer) -> None:
    freezer.move_to(NOW)
    await setup(hass, make_entry())

    board_calls = [c for c in mock_api.mock_calls if "departureboards" in str(c[1])]
    assert board_calls
    _, url, _, headers = board_calls[0]
    assert headers["X-Access-Token"] == "secret"
    assert "ids%5B%5D=U1072Z101P" in str(url) or "ids[]=U1072Z101P" in str(url)


async def test_auth_failure_starts_reauth(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(f"{API}/v2/pid/departureboards", status=401)
    entry = make_entry()
    await setup(hass, entry)

    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert any(f["context"]["source"] == "reauth" for f in hass.config_entries.flow.async_progress())


async def test_api_error_retries_setup(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(f"{API}/v2/pid/departureboards", status=500)
    entry = make_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


@pytest.mark.usefixtures("mock_api")
async def test_unload(hass: HomeAssistant, freezer) -> None:
    freezer.move_to(NOW)
    entry = make_entry()
    await setup(hass, entry)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert hass.states.get("sensor.andel_b").state == "unavailable"


# ---- služby ----


@pytest.mark.usefixtures("mock_api")
async def test_service_get_departures_by_entity(hass: HomeAssistant, freezer) -> None:
    freezer.move_to(NOW)
    await setup(hass, make_entry(routes=["5"]))

    result = await hass.services.async_call(
        DOMAIN,
        "get_departures",
        {"entity_id": "sensor.andel_b"},
        blocking=True,
        return_response=True,
    )
    assert result["stop_id"] == STOP_ID
    assert [d["route"] for d in result["departures"]] == ["5"]
    assert result["infotexts"]


@pytest.mark.usefixtures("mock_api")
async def test_service_get_departures_by_stop_id_with_overrides(
    hass: HomeAssistant, freezer
) -> None:
    freezer.move_to(NOW)
    await setup(hass, make_entry())

    result = await hass.services.async_call(
        DOMAIN,
        "get_departures",
        {"stop_id": STOP_ID, "routes": ["N91", "12"], "limit": 1},
        blocking=True,
        return_response=True,
    )
    assert [d["route"] for d in result["departures"]] == ["12"]


@pytest.mark.usefixtures("mock_api")
async def test_service_get_departures_requires_one_target(hass: HomeAssistant, freezer) -> None:
    freezer.move_to(NOW)
    await setup(hass, make_entry())

    for data in ({}, {"entity_id": "sensor.andel_b", "stop_id": STOP_ID}):
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                DOMAIN, "get_departures", data, blocking=True, return_response=True
            )


async def test_service_refresh(hass: HomeAssistant, mock_api, freezer) -> None:
    freezer.move_to(NOW)
    await setup(hass, make_entry())
    before = len([c for c in mock_api.mock_calls if "departureboards" in str(c[1])])

    await hass.services.async_call(
        DOMAIN, "refresh", {"entity_id": ["sensor.andel_b"]}, blocking=True
    )
    await hass.async_block_till_done()
    after = len([c for c in mock_api.mock_calls if "departureboards" in str(c[1])])
    assert after == before + 1
