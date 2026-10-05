"""Testy `golemio_api.py` — bez HA, importováno jako bare modul.

Klient se testuje proti lokálnímu aiohttp serveru (funguje i na Windows bez HA).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer
import pytest

INTEGRATION_DIR = (
    Path(__file__).resolve().parent.parent / "custom_components" / "pid_departure_boards"
)
sys.path.insert(0, str(INTEGRATION_DIR))
try:
    import golemio_api
finally:
    sys.path.remove(str(INTEGRATION_DIR))

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "departureboards.json").read_text("utf-8"))


@pytest.fixture(autouse=True)
def _allow_sockets(request):
    """Plugin HA blokuje sockety; tyhle testy potřebují lokální server (bez pluginu nic nedělá)."""
    if "socket_enabled" in request.session._fixturemanager._arg2fixturedefs:
        request.getfixturevalue("socket_enabled")


class FakeApi:
    """Zaznamenává dotazy a odpovídá podle `routes` (cesta → (status, payload) nebo callable)."""

    def __init__(self) -> None:
        self.requests: list[web.Request] = []
        self.routes: dict = {}

    async def handle(self, request: web.Request) -> web.StreamResponse:
        self.requests.append(request)
        route = self.routes[request.path]
        if callable(route):
            route = route(request)
        status, payload = route
        return web.json_response(payload, status=status)


@pytest.fixture
async def api():
    fake = FakeApi()
    app = web.Application()
    app.router.add_get("/{tail:.*}", fake.handle)
    server = TestServer(app)
    await server.start_server()
    async with aiohttp.ClientSession() as session:
        fake.client = golemio_api.GolemioClient(
            session, "secret-key", base_url=str(server.make_url(""))
        )
        yield fake
    await server.close()


async def test_get_departures_sends_token_and_params(api):
    api.routes["/v2/pid/departureboards"] = (200, FIXTURE)
    data = await api.client.async_get_departures(
        ["U1", "U2"], minutes_after=240, limit=20, route_filter="routeHeadingOnce"
    )
    assert data["departures"]

    (request,) = api.requests
    assert request.headers["X-Access-Token"] == "secret-key"
    assert request.query.getall("ids[]") == ["U1", "U2"]
    assert request.query["minutesAfter"] == "240"
    assert request.query["limit"] == "20"
    assert request.query["order"] == "real"
    assert request.query["filter"] == "routeHeadingOnce"


async def test_no_filter_param_by_default(api):
    api.routes["/v2/pid/departureboards"] = (200, FIXTURE)
    await api.client.async_get_departures(["U1"], minutes_after=60, limit=5)
    assert "filter" not in api.requests[0].query


@pytest.mark.parametrize(
    ("status", "exc"),
    [
        (401, golemio_api.GolemioAuthError),
        (403, golemio_api.GolemioAuthError),
        (429, golemio_api.GolemioRateLimitError),
        (500, golemio_api.GolemioConnectionError),
        (404, golemio_api.GolemioConnectionError),
    ],
)
async def test_http_errors(api, status, exc):
    api.routes["/v2/pid/departureboards"] = (status, {"error": "x"})
    with pytest.raises(exc):
        await api.client.async_get_departures(["U1"], minutes_after=60, limit=5)


async def test_network_error():
    async with aiohttp.ClientSession() as session:
        # nic na portu neposlouchá
        client = golemio_api.GolemioClient(session, "k", base_url="http://127.0.0.1:1")
        with pytest.raises(golemio_api.GolemioConnectionError):
            await client.async_get_departures(["U1"], minutes_after=60, limit=5)


async def test_unexpected_departures_payload(api):
    api.routes["/v2/pid/departureboards"] = (200, ["not", "a", "dict"])
    with pytest.raises(golemio_api.GolemioConnectionError):
        await api.client.async_get_departures(["U1"], minutes_after=60, limit=5)


async def test_validate(api):
    api.routes["/v2/gtfs/stops"] = (200, {"features": []})
    await api.client.async_validate()
    assert api.requests[0].query["limit"] == "1"
    assert api.requests[0].headers["X-Access-Token"] == "secret-key"


async def test_validate_bad_key(api):
    api.routes["/v2/gtfs/stops"] = (401, {})
    with pytest.raises(golemio_api.GolemioAuthError):
        await api.client.async_validate()


async def test_get_stops_paginates(api, monkeypatch):
    monkeypatch.setattr(golemio_api, "STOPS_PAGE_SIZE", 2)
    pages = {
        "0": {"features": [{"properties": {"stop_id": "A"}}, {"properties": {"stop_id": "B"}}]},
        "2": {"features": [{"properties": {"stop_id": "C"}}]},
    }
    api.routes["/v2/gtfs/stops"] = lambda r: (200, pages[r.query["offset"]])
    stops = await api.client.async_get_stops()
    assert [s["stop_id"] for s in stops] == ["A", "B", "C"]
    assert [r.query["offset"] for r in api.requests] == ["0", "2"]


async def test_get_stops_unexpected_payload(api):
    api.routes["/v2/gtfs/stops"] = (200, {"nope": 1})
    with pytest.raises(golemio_api.GolemioConnectionError):
        await api.client.async_get_stops()
