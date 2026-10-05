"""Testy `models.py` — bez HA, importováno jako bare modul."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

INTEGRATION_DIR = (
    Path(__file__).resolve().parent.parent / "custom_components" / "pid_departure_boards"
)
# Nepřidávat do pyproject `pythonpath` — a celý balíček neimportovat (`__init__.py`
# importuje homeassistant, které na Windows nejde načíst kvůli `fcntl`).
sys.path.insert(0, str(INTEGRATION_DIR))
try:
    import models
finally:
    sys.path.remove(str(INTEGRATION_DIR))

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "departureboards.json").read_text("utf-8"))
NOW = datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc)


def test_parse_departures_skips_entries_without_time():
    deps = models.parse_departures(FIXTURE)
    assert [d.route for d in deps] == ["5", "12", "N91"]


def test_departure_fields():
    d = models.parse_departures(FIXTURE)[0]
    assert d.route_type == 0
    assert d.headsign == "Sidliste Barrandov"
    assert d.platform == "B"
    assert d.delay_min == 1
    assert d.wheelchair is True and d.air_conditioned is True
    assert d.last_stop == "Palmovka"
    assert d.departure_time == datetime(2026, 10, 5, 10, 6, 30, tzinfo=timezone.utc)


def test_unknown_delay_and_flags():
    d = models.parse_departures(FIXTURE)[1]
    assert d.delay_min is None
    assert d.departure_time == d.scheduled  # bez predikce platí jízdní řád
    assert d.air_conditioned is None
    assert d.canceled and d.at_stop and d.is_substitute
    assert not d.is_night and not d.is_regional


def test_night_regional_flags():
    d = models.parse_departures(FIXTURE)[2]
    assert d.is_night and d.is_regional
    assert d.air_conditioned is False


def test_as_dict_is_json_serializable():
    for d in models.parse_departures(FIXTURE):
        json.dumps(d.as_dict())


def test_filter_departures_by_route_and_limit():
    deps = models.parse_departures(FIXTURE)
    assert [d.route for d in models.filter_departures(deps, {"5", "N91"}, 10)] == ["5", "N91"]
    # řazeno podle času (12 jede dřív než 5), prázdný výběr = všechny
    assert [d.route for d in models.filter_departures(deps, set(), 2)] == ["12", "5"]


def test_parse_infotexts_filters_stop_and_validity():
    infos = models.parse_infotexts(FIXTURE, {"U1072Z101P"}, NOW)
    assert [i.text for i in infos] == ["Vyluka tramvaje 5", "Obecny text"]


def test_infotext_language():
    info = models.parse_infotexts(FIXTURE, {"U1072Z101P"}, NOW)[0]
    assert info.as_dict("cs")["text"] == "Vyluka tramvaje 5"
    assert info.as_dict("en")["text"] == "Tram 5 diversion"
    # fallback na text, když chybí anglická verze
    assert models.parse_infotexts(FIXTURE, {"U1072Z101P"}, NOW)[1].as_dict("en")["text"] == "Obecny text"


def test_empty_response():
    assert models.parse_departures({}) == []
    assert models.parse_infotexts({}, {"x"}, NOW) == []
