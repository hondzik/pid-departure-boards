"""Fixtures pro testy vyžadující Home Assistant.

Poznámka: `homeassistant` core (a tedy `pytest-homeassistant-custom-component`) importuje na
modulové úrovni `fcntl`, který na Windows neexistuje — testy s fixturou `hass` proto na
nativním Windows Pythonu nejdou spustit. Lokálně přes WSL, v CI běží na `ubuntu-latest`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

try:
    import pytest_homeassistant_custom_component  # noqa: F401

    pytest_plugins = "pytest_homeassistant_custom_component"
except ImportError:
    # Bez tohohle guardu by na Windows spadlo i spuštění testů, které `hass` nepoužívají
    # (např. test_translations.py).
    pytest_plugins = []

FIXTURES = Path(__file__).parent / "fixtures"
API = "https://api.golemio.cz"


@pytest.fixture(autouse=True)
def auto_ha_fixtures(request):
    """Líně dotáhne `enable_custom_integrations`, aby HA loader našel
    `custom_components/pid_departure_boards` — jen když test používá `hass`."""
    if "hass" in request.fixturenames:
        request.getfixturevalue("enable_custom_integrations")
    yield


@pytest.fixture
def departureboards() -> dict:
    return json.loads((FIXTURES / "departureboards.json").read_text("utf-8"))


@pytest.fixture
def stops_payload() -> dict:
    def feature(stop_id: str, name: str, platform: str | None, location_type: int = 0):
        return {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [14.4036, 50.0716]},  # lon, lat
            "properties": {
                "stop_id": stop_id,
                "stop_name": name,
                "platform_code": platform,
                "location_type": location_type,
            },
        }

    return {
        "type": "FeatureCollection",
        "features": [
            feature("U1072Z101P", "Anděl", "B"),
            feature("U1072Z102P", "Anděl", "D"),
            feature("U1072S1", "Anděl", None, location_type=1),  # stanice — vyřadit
            feature("U1072Z103P_210401", "Anděl", "X"),  # platné až v budoucnu — vyřadit
            feature("U2Z1P", "Andělská", "A"),
            feature("U3Z1P", "Palmovka", "A"),
        ],
    }


@pytest.fixture
def mock_api(aioclient_mock, departureboards, stops_payload):
    """Golemio API vracející ukázková data."""
    aioclient_mock.get(f"{API}/v2/gtfs/stops", json=stops_payload)
    aioclient_mock.get(f"{API}/v2/pid/departureboards", json=departureboards)
    return aioclient_mock


@pytest.fixture
def mock_setup_entry():
    """Config flow netestuje setup entry."""
    from unittest.mock import patch

    with patch(
        "custom_components.pid_departure_boards.async_setup_entry", return_value=True
    ) as mock:
        yield mock
