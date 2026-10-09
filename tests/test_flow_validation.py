"""Neplatný vstup do formulářů musí skončit chybou formuláře, ne neošetřenou výjimkou.

Jádro HA 2026.10 validuje formuláře přes `probatio`; schémata z `voluptuous` musí
dál vracet validační chyby, které jádro umí zpracovat.
"""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import InvalidData

from custom_components.pid_departure_boards.const import DOMAIN

from .test_init import make_entry, setup


async def test_user_flow_missing_api_key(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    with pytest.raises(InvalidData) as err:
        await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert "api_key" in err.value.schema_errors


@pytest.mark.usefixtures("mock_api")
async def test_options_flow_interval_below_minimum(hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2026-10-05T10:00:00+00:00")
    entry = make_entry()
    await setup(hass, entry)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    with pytest.raises(InvalidData) as err:
        await hass.config_entries.options.async_configure(
            result["flow_id"], {"scan_interval": 1}
        )
    assert "scan_interval" in err.value.schema_errors


@pytest.mark.usefixtures("mock_api")
async def test_subentry_flow_missing_query(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={"api_key": "secret"}, unique_id="abc")
    entry.add_to_hass(hass)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "stop"), context={"source": "user"}
    )
    with pytest.raises(InvalidData) as err:
        await hass.config_entries.subentries.async_configure(result["flow_id"], {})
    assert "query" in err.value.schema_errors
