"""Trasy a vozidla: modely nad skutečnými (ořezanými) odpověďmi Golemio, 2026-10-13."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

INTEGRATION_DIR = (
    Path(__file__).resolve().parent.parent / "custom_components" / "pid_departure_boards"
)
sys.path.insert(0, str(INTEGRATION_DIR))
try:
    import models
finally:
    sys.path.remove(str(INTEGRATION_DIR))

REAL = Path(__file__).parent / "fixtures" / "golemio_real"


def real(name: str):
    return json.loads((REAL / name).read_text("utf-8"))


# ---- referenční spoje ----


def make_departure(route, trip_id, headsign, minute, canceled=False) -> models.Departure:
    when = datetime(2026, 10, 13, 15, minute, tzinfo=timezone.utc)
    return models.Departure(
        route=route, route_type=0, headsign=headsign, platform="A", scheduled=when, predicted=None,
        delay_min=None, wheelchair=None, air_conditioned=None, is_night=False, is_regional=False,
        is_substitute=False, canceled=canceled, at_stop=False, trip_id=trip_id, last_stop=None,
        stop_id="U1Z1P",
    )


def test_reference_trips_take_earliest_departure_per_route():
    deps = [
        make_departure("20", "late", "Dědina", 30),
        make_departure("20", "early", "Dědina", 10),
        make_departure("12", "twelve", "Lehovec", 20),
    ]
    assert models.reference_trips(deps, set()) == {
        "20": ("early", "Dědina"),
        "12": ("twelve", "Lehovec"),
    }


def test_reference_trips_only_selected_routes():
    deps = [make_departure("20", "a", "X", 10), make_departure("12", "b", "Y", 20)]
    assert list(models.reference_trips(deps, {"12"})) == ["12"]


def test_reference_trips_prefer_non_canceled_even_if_later():
    deps = [
        make_departure("20", "canceled", "X", 10, canceled=True),
        make_departure("20", "running", "X", 30),
    ]
    assert models.reference_trips(deps, set()) == {"20": ("running", "X")}


def test_reference_trips_fall_back_to_canceled_and_skip_missing_trip_id():
    deps = [
        make_departure("20", "canceled", "X", 10, canceled=True),
        make_departure("12", None, "Y", 10),
    ]
    assert models.reference_trips(deps, set()) == {"20": ("canceled", "X")}


def test_reference_trips_from_real_board():
    deps = models.parse_departures(real("departureboards.json"))
    refs = models.reference_trips(deps, set())
    assert refs["20"] == ("20_17883_261005", "Dědina")
    assert set(refs) == {d.route for d in deps}


# ---- spoj a trasa ----


def test_parse_trip_info_from_real_trip():
    info = models.parse_trip_info(real("trip_with_shapes.json"))
    assert info == models.TripInfo(
        trip_id="20_17883_261005", shape_id="L20V2", direction_id=0, headsign="Dědina"
    )


def test_parse_trip_info_invalid():
    assert models.parse_trip_info({}) is None
    assert models.parse_trip_info(["x"]) is None  # type: ignore[arg-type]
    info = models.parse_trip_info({"trip_id": "t"})
    assert info is not None and info.shape_id is None and info.direction_id is None


def test_parse_shape_points_orders_by_sequence_and_keeps_lon_lat():
    original = models.parse_shape_points(real("shape.json"))
    data = real("shape.json")
    data["features"].reverse()  # pořadí v odpovědi se nesmí spoléhat
    assert models.parse_shape_points(data) == original
    assert len(original) == 3
    lon, lat = original[0]
    assert 14 < lon < 15 and 49 < lat < 51  # GeoJSON: [lon, lat]


def test_parse_shape_points_ignores_broken_features():
    assert models.parse_shape_points({}) == []
    assert models.parse_shape_points({"features": [{"geometry": None}, {"properties": {}}]}) == []


# ---- vozidla ----


def test_parse_vehicles_from_real_response():
    vehicles = models.parse_vehicles(real("vehiclepositions.json"))
    assert len(vehicles) == 2
    first = vehicles[0]
    assert first.route == "20"
    assert first.headsign in {"Radlická", "Dědina"}
    assert 14 < first.longitude < 15 and 49 < first.latitude < 51
    assert first.trip_id and first.vehicle_id
    assert first.state in {"at_stop", "on_track"}
    assert isinstance(first.bearing, int)
    assert isinstance(first.delay_min, int)  # sekundy → minuty
    assert first.canceled is False
    json.dumps(first.as_dict())


def test_vehicle_delay_is_converted_from_seconds():
    feature = real("vehiclepositions.json")["features"][0]
    feature["properties"]["last_position"]["delay"]["actual"] = 140
    assert models.parse_vehicle(feature).delay_min == 2
    feature["properties"]["last_position"]["delay"]["actual"] = 160
    assert models.parse_vehicle(feature).delay_min == 3
    feature["properties"]["last_position"]["delay"]["actual"] = -60
    assert models.parse_vehicle(feature).delay_min == -1
    feature["properties"]["last_position"]["delay"] = None
    assert models.parse_vehicle(feature).delay_min is None


def test_vehicle_without_position_is_dropped():
    feature = real("vehiclepositions.json")["features"][0]
    feature["geometry"] = None
    assert models.parse_vehicle(feature) is None
    assert models.parse_vehicles({"features": [feature]}) == []
    assert models.parse_vehicles({}) == []


def test_filter_vehicles_by_route_and_headsign():
    vehicles = models.parse_vehicles(real("vehiclepositions.json"))
    toward = vehicles[0].headsign
    result = models.filter_vehicles(vehicles, "20", toward)
    assert result and all(v.headsign == toward for v in result)
    assert len(result) < len(vehicles)  # druhý směr je pryč
    assert models.filter_vehicles(vehicles, "99", toward) == []


def test_filter_vehicles_ignores_case_and_whitespace_and_none_means_any():
    vehicles = models.parse_vehicles(real("vehiclepositions.json"))
    target = vehicles[0].headsign
    assert models.filter_vehicles(vehicles, "20", f"  {target.upper()} ")
    assert len(models.filter_vehicles(vehicles, "20", None)) == len(vehicles)


def test_route_sort_key():
    assert sorted(["N91", "12", "5", "X1", "100"], key=models.route_sort_key) == [
        "5", "12", "100", "N91", "X1",
    ]
