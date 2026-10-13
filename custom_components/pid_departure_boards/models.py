"""Datový model odpovědi Golemio departureboards. Bez importu homeassistant.*."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


def _parse_dt(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@dataclass(frozen=True)
class Departure:
    """Jeden odjezd z nástupiště."""

    route: str
    route_type: int | None
    headsign: str | None
    platform: str | None
    scheduled: datetime | None
    predicted: datetime | None
    delay_min: int | None  # None, pokud API zpoždění nezná
    wheelchair: bool | None
    air_conditioned: bool | None
    is_night: bool
    is_regional: bool
    is_substitute: bool
    canceled: bool
    at_stop: bool
    trip_id: str | None
    last_stop: str | None
    stop_id: str | None

    @property
    def departure_time(self) -> datetime | None:
        """Predikovaný čas, jinak jízdní řád."""
        return self.predicted or self.scheduled

    def as_dict(self) -> dict[str, Any]:
        """Serializace pro atribut entity / odpověď služby (časy jako ISO)."""
        return {
            "route": self.route,
            "route_type": self.route_type,
            "headsign": self.headsign,
            "platform": self.platform,
            "scheduled": self.scheduled.isoformat() if self.scheduled else None,
            "predicted": self.predicted.isoformat() if self.predicted else None,
            "delay_min": self.delay_min,
            "wheelchair": self.wheelchair,
            "air_conditioned": self.air_conditioned,
            "is_night": self.is_night,
            "is_regional": self.is_regional,
            "is_substitute": self.is_substitute,
            "canceled": self.canceled,
            "at_stop": self.at_stop,
            "trip_id": self.trip_id,
            "last_stop": self.last_stop,
        }


@dataclass(frozen=True)
class Infotext:
    """Informační text (výluka, mimořádnost)."""

    text: str
    text_en: str | None
    valid_from: datetime | None
    valid_to: datetime | None
    display_type: str | None
    related_stops: tuple[str, ...]

    def is_valid(self, now: datetime) -> bool:
        if self.valid_from and now < self.valid_from:
            return False
        if self.valid_to and now > self.valid_to:
            return False
        return True

    def as_dict(self, language: str | None = None) -> dict[str, Any]:
        text = self.text
        if language and language.startswith("en") and self.text_en:
            text = self.text_en
        return {
            "text": text,
            "valid_from": self.valid_from.isoformat() if self.valid_from else None,
            "valid_to": self.valid_to.isoformat() if self.valid_to else None,
            "display_type": self.display_type,
        }


def _timestamp(block: Any) -> tuple[datetime | None, datetime | None]:
    """Vrátí (scheduled, predicted) z `departure_timestamp`/`arrival_timestamp`."""
    if not isinstance(block, dict):
        return None, None
    return _parse_dt(block.get("scheduled")), _parse_dt(block.get("predicted"))


def parse_departure(item: dict[str, Any]) -> Departure:
    route = item.get("route") or {}
    trip = item.get("trip") or {}
    stop = item.get("stop") or {}
    delay = item.get("delay") or {}
    last_stop = item.get("last_stop") or {}

    scheduled, predicted = _timestamp(item.get("departure_timestamp"))
    if scheduled is None and predicted is None:
        scheduled, predicted = _timestamp(item.get("arrival_timestamp"))

    delay_min: int | None = None
    if delay.get("is_available"):
        minutes = delay.get("minutes")
        if isinstance(minutes, (int, float)):
            delay_min = int(minutes)

    route_type = route.get("type")
    return Departure(
        route=str(route.get("short_name") or ""),
        route_type=route_type if isinstance(route_type, int) else None,
        headsign=trip.get("headsign"),
        platform=stop.get("platform_code"),
        scheduled=scheduled,
        predicted=predicted,
        delay_min=delay_min,
        wheelchair=trip.get("is_wheelchair_accessible"),
        air_conditioned=trip.get("is_air_conditioned"),
        is_night=bool(route.get("is_night")),
        is_regional=bool(route.get("is_regional")),
        is_substitute=bool(route.get("is_substitute_transport")),
        canceled=bool(trip.get("is_canceled")),
        at_stop=bool(trip.get("is_at_stop")),
        trip_id=trip.get("id"),
        last_stop=last_stop.get("name"),
        stop_id=stop.get("id"),
    )


def parse_departures(data: dict[str, Any]) -> list[Departure]:
    """Odjezdy z odpovědi `/v2/pid/departureboards`, bez záznamů bez času."""
    result = []
    for item in data.get("departures") or []:
        dep = parse_departure(item)
        if dep.departure_time is not None:
            result.append(dep)
    return result


def parse_infotexts(
    data: dict[str, Any], stop_ids: set[str], now: datetime
) -> list[Infotext]:
    """Platné infotexty týkající se některého ze `stop_ids`.

    Text bez `related_stops` bere jako obecný (platí pro všechny zastávky z dotazu).
    Formát `related_stops` (řetězce, nebo objekty s `id`) ve specifikaci není popsán
    jednoznačně, proto se zpracují obě varianty.
    """
    result = []
    for item in data.get("infotexts") or []:
        related_ids = tuple(
            r if isinstance(r, str) else str(r.get("id", ""))
            for r in (item.get("related_stops") or [])
            if isinstance(r, (str, dict))
        )
        if related_ids and not stop_ids.intersection(related_ids):
            continue
        info = Infotext(
            text=item.get("text") or "",
            text_en=item.get("text_en"),
            valid_from=_parse_dt(item.get("valid_from")),
            valid_to=_parse_dt(item.get("valid_to")),
            display_type=item.get("display_type"),
            related_stops=related_ids,
        )
        if info.text and info.is_valid(now):
            result.append(info)
    return result


def filter_departures(
    departures: list[Departure], routes: set[str] | frozenset[str], limit: int
) -> list[Departure]:
    """Vybere `limit` nejbližších odjezdů ze zadaných linek (prázdné = všechny)."""
    selected = [d for d in departures if not routes or d.route in routes]
    selected.sort(key=lambda d: d.departure_time)
    return selected[:limit]


def route_sort_key(route: str) -> tuple[int, int, str]:
    """Číselné linky podle čísla, ostatní (N91, X1) abecedně za nimi."""
    return (0, int(route), "") if route.isdigit() else (1, 0, route)


def reference_trips(
    departures: list[Departure], routes: set[str] | frozenset[str]
) -> dict[str, tuple[str, str | None]]:
    """Linka → (`trip_id`, cíl) nejbližšího odjezdu z nástupiště.

    Spoj odjíždějící z tohoto nástupiště jede z definice sledovaným směrem; podle něj se
    určuje trasa a směr vozidel. Zrušený spoj se bere jen jako poslední možnost. Prázdný
    výběr linek = všechny linky z odjezdů.
    """
    chosen: dict[str, Departure] = {}
    for dep in sorted(departures, key=lambda d: (d.canceled, d.departure_time)):
        if not dep.trip_id or not dep.route or (routes and dep.route not in routes):
            continue
        chosen.setdefault(dep.route, dep)
    return {route: (dep.trip_id, dep.headsign) for route, dep in chosen.items()}


@dataclass(frozen=True)
class TripInfo:
    """Údaje GTFS spoje potřebné pro trasu."""

    trip_id: str
    shape_id: str | None
    direction_id: int | None
    headsign: str | None


def parse_trip_info(data: dict[str, Any]) -> TripInfo | None:
    """`GET /v2/gtfs/trips/{id}` (bez `includeShapes`)."""
    if not isinstance(data, dict) or not data.get("trip_id"):
        return None
    direction = data.get("direction_id")
    return TripInfo(
        trip_id=data["trip_id"],
        shape_id=data.get("shape_id"),
        direction_id=direction if isinstance(direction, int) else None,
        headsign=data.get("trip_headsign"),
    )


def parse_shape_points(data: dict[str, Any]) -> list[tuple[float, float]]:
    """Body trasy `(lon, lat)` podle `shape_pt_sequence` z `GET /v2/gtfs/shapes/{id}`."""
    points: list[tuple[int, float, float]] = []
    for feature in data.get("features") or []:
        coords = (feature.get("geometry") or {}).get("coordinates")
        sequence = (feature.get("properties") or {}).get("shape_pt_sequence")
        if isinstance(coords, list) and len(coords) >= 2 and isinstance(sequence, int):
            points.append((sequence, float(coords[0]), float(coords[1])))
    points.sort()
    return [(lon, lat) for _, lon, lat in points]


@dataclass(frozen=True)
class RouteShape:
    """Zjednodušená trasa spoje; `coordinates` jsou `[lon, lat]` jako v GeoJSON."""

    shape_id: str
    headsign: str | None
    direction_id: int | None
    coordinates: list[list[float]]


@dataclass(frozen=True)
class Vehicle:
    """Poloha vozidla."""

    vehicle_id: str | None
    route: str
    trip_id: str | None
    headsign: str | None
    latitude: float
    longitude: float
    bearing: int | None
    delay_min: int | None
    state: str | None  # at_stop | on_track
    canceled: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "vehicle_id": self.vehicle_id,
            "route": self.route,
            "trip_id": self.trip_id,
            "headsign": self.headsign,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "bearing": self.bearing,
            "delay_min": self.delay_min,
            "state": self.state,
            "canceled": self.canceled,
        }


def parse_vehicle(feature: dict[str, Any]) -> Vehicle | None:
    """Jedno vozidlo z `GET /v2/vehiclepositions`; bez platné polohy vrací `None`."""
    coords = (feature.get("geometry") or {}).get("coordinates")
    if not (isinstance(coords, list) and len(coords) >= 2):
        return None
    props = feature.get("properties") or {}
    last = props.get("last_position") or {}
    trip = props.get("trip") or {}
    gtfs = trip.get("gtfs") or {}

    delay_s = (last.get("delay") or {}).get("actual")
    bearing = last.get("bearing")
    registration = trip.get("vehicle_registration_number")
    return Vehicle(
        vehicle_id=str(registration) if registration is not None else None,
        route=str(gtfs.get("route_short_name") or ""),
        trip_id=gtfs.get("trip_id"),
        headsign=gtfs.get("trip_headsign"),
        longitude=float(coords[0]),  # GeoJSON: lon, lat
        latitude=float(coords[1]),
        bearing=int(bearing) if isinstance(bearing, (int, float)) else None,
        delay_min=round(delay_s / 60) if isinstance(delay_s, (int, float)) else None,
        state=last.get("state_position"),
        canceled=bool(last.get("is_canceled")),
    )


def parse_vehicles(data: dict[str, Any]) -> list[Vehicle]:
    vehicles = (parse_vehicle(f) for f in data.get("features") or [])
    return [v for v in vehicles if v is not None]


def filter_vehicles(vehicles: list[Vehicle], route: str, headsign: str | None) -> list[Vehicle]:
    """Vozidla dané linky jedoucí k danému cíli (= stejným směrem jako referenční spoj)."""
    wanted = _normalize_headsign(headsign)
    return [
        v
        for v in vehicles
        if v.route == route and (wanted is None or _normalize_headsign(v.headsign) == wanted)
    ]


def _normalize_headsign(headsign: str | None) -> str | None:
    return " ".join(headsign.split()).casefold() if headsign and headsign.strip() else None
