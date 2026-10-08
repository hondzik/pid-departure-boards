"""Index zastávek pro vyhledávání v config flow. Bez importu homeassistant.*."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# GTFS stop_id platné až v budoucnu má datovou příponu, např. `U476Z51P_210401`
_FUTURE_SUFFIX = re.compile(r"_\d{6}$")


def normalize(text: str) -> str:
    """Malá písmena a bez diakritiky — pro vyhledávání."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c)).strip()


def slim_stops(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Z `properties` zastávek nechá jen nástupiště (location_type 0) a potřebná pole."""
    result = []
    for props in raw:
        stop_id = props.get("stop_id")
        name = props.get("stop_name")
        if not stop_id or not name or _FUTURE_SUFFIX.search(stop_id):
            continue
        if props.get("location_type") not in (0, None):
            continue
        result.append(
            {
                "stop_id": stop_id,
                "stop_name": name,
                "platform_code": props.get("platform_code"),
                "lat": props.get("stop_lat"),
                "lon": props.get("stop_lon"),
            }
        )
    return result


class StopIndex:
    """Zastávky seskupené podle jména (jedno jméno = víc nástupišť)."""

    def __init__(self, stops: list[dict[str, Any]]) -> None:
        self._by_name: dict[str, list[str]] = {}
        self._platforms: dict[str, str | None] = {}
        self._coordinates: dict[str, tuple[float, float]] = {}
        for stop in stops:
            self._by_name.setdefault(stop["stop_name"], []).append(stop["stop_id"])
            self._platforms[stop["stop_id"]] = stop.get("platform_code")
            lat, lon = stop.get("lat"), stop.get("lon")
            if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                self._coordinates[stop["stop_id"]] = (float(lat), float(lon))
        self._normalized = {name: normalize(name) for name in self._by_name}

    def __len__(self) -> int:
        return len(self._by_name)

    def search(self, query: str, limit: int = 50) -> list[str]:
        """Jména zastávek obsahující `query`; začátek jména má přednost."""
        q = normalize(query)
        if not q:
            return []
        starts, contains = [], []
        for name, norm in self._normalized.items():
            if norm.startswith(q):
                starts.append(name)
            elif q in norm:
                contains.append(name)
        return (sorted(starts) + sorted(contains))[:limit]

    def stop_ids_for(self, name: str) -> list[str]:
        return sorted(self._by_name.get(name, []))

    def coordinates(self, stop_id: str) -> tuple[float, float] | None:
        """(latitude, longitude) nástupiště, pokud je známá."""
        return self._coordinates.get(stop_id)

    def platform_code(self, stop_id: str) -> str | None:
        return self._platforms.get(stop_id)
