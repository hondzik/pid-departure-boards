"""Config flow: token, options, subentry nástupiště."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.pid_departure_boards.const import DOMAIN

from .conftest import API
from .test_init import STOP_ID, make_entry, setup


# ---- token ----


@pytest.mark.usefixtures("mock_api", "mock_setup_entry")
async def test_user_flow_creates_entry(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"api_key": " key "})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"api_key": "key"}


@pytest.mark.parametrize(
    ("status", "error"), [(401, "invalid_auth"), (500, "cannot_connect")]
)
async def test_user_flow_errors(hass: HomeAssistant, aioclient_mock, status, error) -> None:
    aioclient_mock.get(f"{API}/v2/gtfs/stops", status=status)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"api_key": "x"})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}


@pytest.mark.usefixtures("mock_api", "mock_setup_entry")
async def test_user_flow_duplicate_key(hass: HomeAssistant) -> None:
    for expected in (FlowResultType.CREATE_ENTRY, FlowResultType.ABORT):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"api_key": "same"}
        )
        assert result["type"] is expected


@pytest.mark.usefixtures("mock_api")
async def test_reauth_flow(hass: HomeAssistant, mock_setup_entry) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={"api_key": "old"}, unique_id="old")
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"api_key": "new"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["api_key"] == "new"


# ---- options ----


@pytest.mark.usefixtures("mock_api")
async def test_options_flow_sets_interval(hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2026-10-05T10:00:00+00:00")
    entry = make_entry()
    await setup(hass, entry)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"scan_interval": 120}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {"scan_interval": 120}
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


# ---- subentry „nástupiště“ ----


async def _start_subentry(hass: HomeAssistant, entry: MockConfigEntry):
    return await hass.config_entries.subentries.async_init(
        (entry.entry_id, "stop"), context={"source": "user"}
    )


@pytest.fixture
def empty_entry(hass: HomeAssistant, mock_api) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={"api_key": "secret"}, unique_id="abc")
    entry.add_to_hass(hass)
    return entry


async def test_add_stop_full_flow(hass: HomeAssistant, empty_entry, freezer) -> None:
    freezer.move_to("2026-10-05T10:00:00+00:00")
    flow = hass.config_entries.subentries

    result = await _start_subentry(hass, empty_entry)
    assert result["step_id"] == "user"

    # bez diakritiky a malými písmeny; „Andělská“ se nabídne také, začátek jména má přednost
    result = await flow.async_configure(result["flow_id"], {"query": "andel"})
    assert result["step_id"] == "pick"
    options = result["data_schema"].schema["stop_choice"].config["options"]
    assert options == ["Anděl", "Andělská"]

    result = await flow.async_configure(result["flow_id"], {"stop_choice": "Anděl"})
    assert result["step_id"] == "platform"
    platforms = {
        o["value"]: o["label"]
        for o in result["data_schema"].schema["stop_id"].config["options"]
    }
    # stanice a stop s datovou příponou jsou vyřazené, B má odjezdy, D ne
    assert set(platforms) == {"U1072Z101P", "U1072Z102P"}
    assert "Sidliste Barrandov" in platforms["U1072Z101P"]
    assert "5" in platforms["U1072Z101P"]

    result = await flow.async_configure(result["flow_id"], {"stop_id": STOP_ID})
    assert result["step_id"] == "routes"
    assert result["data_schema"].schema["routes"].config["options"] == ["5", "12", "N91"]

    result = await flow.async_configure(result["flow_id"], {"routes": ["5", "N91"]})
    assert result["step_id"] == "settings"

    result = await flow.async_configure(
        result["flow_id"], {"name": "Anděl B", "limit": 3, "scan_interval": 45}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Anděl B"

    (subentry,) = empty_entry.subentries.values()
    assert subentry.unique_id == STOP_ID
    assert subentry.data == {
        "stop_id": STOP_ID,
        "stop_name": "Anděl",
        "platform": "B",
        "routes": ["5", "N91"],
        "limit": 3,
        "scan_interval": 45,
        "latitude": 50.0716,
        "longitude": 14.4036,
    }


async def test_add_stop_no_results(hass: HomeAssistant, empty_entry) -> None:
    result = await _start_subentry(hass, empty_entry)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"query": "neexistuje"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"query": "no_results"}


async def test_add_stop_duplicate_platform(hass: HomeAssistant, mock_api, freezer) -> None:
    freezer.move_to("2026-10-05T10:00:00+00:00")
    entry = make_entry()
    await setup(hass, entry)
    flow = hass.config_entries.subentries

    result = await _start_subentry(hass, entry)
    result = await flow.async_configure(result["flow_id"], {"query": "andel"})
    result = await flow.async_configure(result["flow_id"], {"stop_choice": "Anděl"})
    result = await flow.async_configure(result["flow_id"], {"stop_id": STOP_ID})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure_stop(hass: HomeAssistant, mock_api, freezer) -> None:
    freezer.move_to("2026-10-05T10:00:00+00:00")
    entry = make_entry(routes=["5"], limit=5, scan_interval=45)
    await setup(hass, entry)
    (subentry_id,) = entry.subentries

    result = await entry.start_subentry_reconfigure_flow(hass, subentry_id)
    assert result["step_id"] == "reconfigure"
    # nabídnuté linky = zjištěné + už vybrané
    assert result["data_schema"].schema["routes"].config["options"] == ["5", "12", "N91"]

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"routes": ["12"], "limit": 2}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()

    data = entry.subentries[subentry_id].data
    assert data["routes"] == ["12"] and data["limit"] == 2
    assert "scan_interval" not in data  # prázdné pole = výchozí interval
    assert data["stop_id"] == STOP_ID
