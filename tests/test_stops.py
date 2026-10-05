"""Testy `stops.py` — bez HA, importováno jako bare modul."""

from __future__ import annotations

from pathlib import Path
import sys

INTEGRATION_DIR = (
    Path(__file__).resolve().parent.parent / "custom_components" / "pid_departure_boards"
)
sys.path.insert(0, str(INTEGRATION_DIR))
try:
    import stops
finally:
    sys.path.remove(str(INTEGRATION_DIR))


def props(stop_id, name, platform=None, location_type=0):
    return {
        "stop_id": stop_id,
        "stop_name": name,
        "platform_code": platform,
        "location_type": location_type,
    }


RAW = [
    props("U1Z1P", "Anděl", "B"),
    props("U1Z2P", "Anděl", "D"),
    props("U1S1", "Anděl", None, location_type=1),
    props("U1Z3P_210401", "Anděl", "X"),
    props("U2Z1P", "Andělská", "A"),
    props("U3Z1P", "Palmovka", "A"),
    props("U4Z1P", "Malostranské náměstí", "C"),
    {"stop_id": None, "stop_name": "Bez id"},
]


def test_normalize():
    assert stops.normalize("  Anděl ") == "andel"
    assert stops.normalize("ŘEPY") == "repy"


def test_slim_stops_drops_stations_future_ids_and_invalid():
    ids = [s["stop_id"] for s in stops.slim_stops(RAW)]
    assert ids == ["U1Z1P", "U1Z2P", "U2Z1P", "U3Z1P", "U4Z1P"]


def test_search_ignores_diacritics_and_prefers_prefix():
    index = stops.StopIndex(stops.slim_stops(RAW))
    assert index.search("andel") == ["Anděl", "Andělská"]
    assert index.search("NÁMĚSTÍ") == ["Malostranské náměstí"]  # shoda uvnitř jména
    assert index.search("") == []
    assert index.search("xyz") == []


def test_search_limit():
    index = stops.StopIndex(stops.slim_stops(RAW))
    assert index.search("a", limit=2) == ["Anděl", "Andělská"]


def test_stop_ids_and_platforms():
    index = stops.StopIndex(stops.slim_stops(RAW))
    assert index.stop_ids_for("Anděl") == ["U1Z1P", "U1Z2P"]
    assert index.stop_ids_for("Neexistuje") == []
    assert index.platform_code("U1Z2P") == "D"
    assert len(index) == 4
