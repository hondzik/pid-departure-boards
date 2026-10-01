"""Fixtures pro testy vyžadující Home Assistant.

Poznámka: `homeassistant` core (a tedy `pytest-homeassistant-custom-component`) importuje na
modulové úrovni `fcntl`, který na Windows neexistuje — testy s fixturou `hass` proto na
nativním Windows Pythonu nejdou spustit. Lokálně přes WSL, v CI běží na `ubuntu-latest`.
"""

from __future__ import annotations

import pytest

try:
    import pytest_homeassistant_custom_component  # noqa: F401

    pytest_plugins = "pytest_homeassistant_custom_component"
except ImportError:
    # Bez tohohle guardu by na Windows spadlo i spuštění testů, které `hass` nepoužívají
    # (např. test_translations.py).
    pytest_plugins = []


@pytest.fixture(autouse=True)
def auto_ha_fixtures(request):
    """Líně dotáhne `enable_custom_integrations`, aby HA loader našel
    `custom_components/pid_departure_boards` — jen když test používá `hass`."""
    if "hass" in request.fixturenames:
        request.getfixturevalue("enable_custom_integrations")
    yield
