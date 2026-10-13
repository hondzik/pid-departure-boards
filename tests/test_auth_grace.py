"""Přechodné HTTP 401 se toleruje; reauth až při trvalém 401."""

from __future__ import annotations

from datetime import timedelta

import pytest

from homeassistant.config_entries import ConfigEntryState, SOURCE_REAUTH
from homeassistant.core import HomeAssistant

from custom_components.pid_departure_boards.const import AUTH_FAILURE_GRACE_MINUTES

from .conftest import API
from .test_init import NOW, make_entry, setup

STOPS_URL = f"{API}/v2/gtfs/stops"
BOARD_URL = f"{API}/v2/pid/departureboards"


def reauth_flows(hass: HomeAssistant) -> list:
    return [f for f in hass.config_entries.flow.async_progress() if f["context"]["source"] == SOURCE_REAUTH]


def respond_401(mock) -> None:
    mock.clear_requests()
    mock.get(BOARD_URL, status=401)


def respond_ok(mock, departureboards) -> None:
    mock.clear_requests()
    mock.get(BOARD_URL, json=departureboards)


async def test_single_401_at_setup_does_not_start_reauth(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(BOARD_URL, status=401)
    entry = make_entry()
    await setup(hass, entry)

    assert entry.state is ConfigEntryState.SETUP_RETRY  # zkusí se znovu, uživatel není rušen
    assert reauth_flows(hass) == []


async def test_persistent_401_at_setup_starts_reauth_after_grace(
    hass: HomeAssistant, aioclient_mock, freezer
) -> None:
    freezer.move_to(NOW)
    aioclient_mock.get(BOARD_URL, status=401)
    entry = make_entry()
    await setup(hass, entry)
    assert reauth_flows(hass) == []

    freezer.tick(timedelta(minutes=AUTH_FAILURE_GRACE_MINUTES, seconds=1))
    await hass.config_entries.async_reload(entry.entry_id)  # jako další pokus o setup
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert len(reauth_flows(hass)) == 1


async def test_transient_401_after_setup_only_marks_entity_unavailable(
    hass: HomeAssistant, mock_api, departureboards, freezer
) -> None:
    freezer.move_to(NOW)
    entry = make_entry()
    await setup(hass, entry)
    (coordinator,) = entry.runtime_data.coordinators.values()
    assert hass.states.get("sensor.andel_b").state != "unavailable"

    respond_401(mock_api)
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get("sensor.andel_b").state == "unavailable"
    assert reauth_flows(hass) == []

    # další dotaz už zase projde → série 401 skončila a sensor se vrátí
    respond_ok(mock_api, departureboards)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.andel_b").state != "unavailable"


async def test_persistent_401_after_setup_starts_reauth(
    hass: HomeAssistant, mock_api, freezer
) -> None:
    freezer.move_to(NOW)
    entry = make_entry()
    await setup(hass, entry)
    (coordinator,) = entry.runtime_data.coordinators.values()

    respond_401(mock_api)
    await coordinator.async_refresh()  # začátek série
    assert reauth_flows(hass) == []

    freezer.tick(timedelta(minutes=AUTH_FAILURE_GRACE_MINUTES, seconds=1))
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert len(reauth_flows(hass)) == 1


async def test_success_between_failures_restarts_the_grace_period(
    hass: HomeAssistant, mock_api, departureboards, freezer
) -> None:
    freezer.move_to(NOW)
    entry = make_entry()
    await setup(hass, entry)
    (coordinator,) = entry.runtime_data.coordinators.values()

    respond_401(mock_api)
    await coordinator.async_refresh()  # 401 č. 1

    freezer.tick(timedelta(minutes=2))
    respond_ok(mock_api, departureboards)
    await coordinator.async_refresh()  # úspěch → série končí

    freezer.tick(timedelta(minutes=2))  # od prvního 401 už uplynulo 4 min, ale série se přerušila
    respond_401(mock_api)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert reauth_flows(hass) == []


@pytest.mark.parametrize("status", [429, 500])
async def test_other_errors_never_start_reauth(
    hass: HomeAssistant, mock_api, freezer, status
) -> None:
    freezer.move_to(NOW)
    entry = make_entry()
    await setup(hass, entry)
    (coordinator,) = entry.runtime_data.coordinators.values()

    mock_api.clear_requests()
    mock_api.get(BOARD_URL, status=status)
    freezer.tick(timedelta(minutes=10))
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert reauth_flows(hass) == []
