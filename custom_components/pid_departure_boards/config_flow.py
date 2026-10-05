"""Config flow: API token, options (globální refresh) a subentry „nástupiště“."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .const import (
    API_KEYS_URL,
    CONF_API_KEY,
    CONF_LIMIT,
    CONF_NAME,
    CONF_PLATFORM,
    CONF_ROUTES,
    CONF_SCAN_INTERVAL,
    CONF_STOP_ID,
    CONF_STOP_NAME,
    DEFAULT_LIMIT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_LIMIT,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    SUBENTRY_TYPE_STOP,
)
from .golemio_api import GolemioAuthError, GolemioClient, GolemioError
from .models import parse_departures
from .stops import StopIndex
from .stops_cache import StopsCache

_LOGGER = logging.getLogger(__name__)

CONF_QUERY = "query"
CONF_STOP_CHOICE = "stop_choice"
DISCOVERY_MINUTES = 360
DISCOVERY_LIMIT = 500
MAX_STOP_IDS_PER_REQUEST = 100


def _interval_selector(minimum: int = MIN_SCAN_INTERVAL) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=minimum,
            max=MAX_SCAN_INTERVAL,
            step=1,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement="s",
        )
    )


def _limit_selector() -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(min=1, max=MAX_LIMIT, step=1, mode=NumberSelectorMode.BOX)
    )


def _route_sort_key(route: str) -> tuple[int, int, str]:
    """Číselné linky podle čísla, ostatní (N91, X1) abecedně za nimi."""
    return (0, int(route), "") if route.isdigit() else (1, 0, route)


async def _validate_key(hass, api_key: str) -> str | None:
    """Vrátí chybový klíč, nebo None, pokud je API klíč v pořádku."""
    client = GolemioClient(async_get_clientsession(hass), api_key)
    try:
        await client.async_validate()
    except GolemioAuthError:
        return "invalid_auth"
    except GolemioError:
        return "cannot_connect"
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Unexpected error while validating API key")
        return "unknown"
    return None


class PidConfigFlow(ConfigFlow, domain=DOMAIN):
    """Přidání API tokenu."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            await self.async_set_unique_id(hashlib.sha256(api_key.encode()).hexdigest()[:16])
            self._abort_if_unique_id_configured()
            if error := await _validate_key(self.hass, api_key):
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title="PID Departure Boards", data={CONF_API_KEY: api_key}
                )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): TextSelector()}),
            errors=errors,
            description_placeholders={"api_keys_url": API_KEYS_URL},
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            if error := await _validate_key(self.hass, api_key):
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(),
                    data_updates={CONF_API_KEY: api_key},
                    unique_id=hashlib.sha256(api_key.encode()).hexdigest()[:16],
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): TextSelector()}),
            errors=errors,
            description_placeholders={"api_keys_url": API_KEYS_URL},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return PidOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_TYPE_STOP: StopSubentryFlow}


class PidOptionsFlow(OptionsFlow):
    """Globální interval obnovy (nástupiště ho mohou přepsat)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL])}
            )
        current = self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {vol.Required(CONF_SCAN_INTERVAL, default=current): _interval_selector()}
            ),
        )


@dataclass
class _PlatformInfo:
    """Nástupiště zjištěné z odjezdů: linky a cíle."""

    code: str | None
    routes: set[str] = field(default_factory=set)
    headsigns: set[str] = field(default_factory=set)

    def label(self) -> str:
        name = f"{self.code} — " if self.code else ""
        headsigns = ", ".join(sorted(self.headsigns)[:3]) or "—"
        routes = ", ".join(sorted(self.routes, key=_route_sort_key)[:8])
        return f"{name}{headsigns} ({routes})" if routes else f"{name}{headsigns}"


class StopSubentryFlow(ConfigSubentryFlow):
    """Přidání / úprava nástupiště."""

    def __init__(self) -> None:
        self._stop_name: str | None = None
        self._stop_ids: list[str] = []
        self._matches: list[str] = []
        self._platforms: dict[str, _PlatformInfo] = {}
        self._stop_id: str | None = None
        self._routes: list[str] = []
        self._selected_routes: list[str] = []
        self._index: StopIndex | None = None

    # ---- pomocné ----

    def _client(self) -> GolemioClient:
        entry = self._get_entry()
        return GolemioClient(async_get_clientsession(self.hass), entry.data[CONF_API_KEY])

    async def _discover(self, stop_ids: list[str]) -> dict[str, _PlatformInfo]:
        """Zjistí linky a cíle jednotlivých nástupišť z odjezdů na několik hodin dopředu."""
        raw = await self._client().async_get_departures(
            stop_ids[:MAX_STOP_IDS_PER_REQUEST],
            minutes_after=DISCOVERY_MINUTES,
            limit=DISCOVERY_LIMIT,
            route_filter="routeHeadingOnce",
        )
        info: dict[str, _PlatformInfo] = {}
        for dep in parse_departures(raw):
            if dep.stop_id not in stop_ids:
                continue
            item = info.setdefault(dep.stop_id, _PlatformInfo(dep.platform))
            item.routes.add(dep.route)
            if dep.headsign:
                item.headsigns.add(dep.headsign)
        return info

    @staticmethod
    def _error(err: Exception) -> str:
        return "invalid_auth" if isinstance(err, GolemioAuthError) else "cannot_connect"

    # ---- přidání ----

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Hledání zastávky podle jména."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                index = await StopsCache(self.hass, self._client()).async_get_index()
            except GolemioError as err:
                errors["base"] = self._error(err)
            else:
                self._matches = index.search(user_input[CONF_QUERY])
                if not self._matches:
                    errors[CONF_QUERY] = "no_results"
                else:
                    self._index = index
                    return await self.async_step_pick()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_QUERY): TextSelector()}),
            errors=errors,
        )

    async def async_step_pick(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Výběr zastávky z nalezených jmen."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._stop_name = user_input[CONF_STOP_CHOICE]
            self._stop_ids = self._index.stop_ids_for(self._stop_name)
            try:
                self._platforms = await self._discover(self._stop_ids)
            except GolemioError as err:
                errors["base"] = self._error(err)
            else:
                # nástupiště bez odjezdů na dohledné době nabídneme také
                for stop_id in self._stop_ids:
                    self._platforms.setdefault(
                        stop_id, _PlatformInfo(self._index.platform_code(stop_id))
                    )
                return await self.async_step_platform()
        return self.async_show_form(
            step_id="pick",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_STOP_CHOICE): SelectSelector(
                        SelectSelectorConfig(
                            options=self._matches, mode=SelectSelectorMode.DROPDOWN
                        )
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_platform(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Výběr nástupiště (= jeden směr)."""
        if user_input is not None:
            self._stop_id = user_input[CONF_STOP_ID]
            if any(
                s.unique_id == self._stop_id for s in self._get_entry().subentries.values()
            ):
                return self.async_abort(reason="already_configured")
            self._routes = sorted(self._platforms[self._stop_id].routes, key=_route_sort_key)
            return await self.async_step_routes()

        options = [
            SelectOptionDict(value=stop_id, label=info.label())
            for stop_id, info in sorted(
                self._platforms.items(), key=lambda kv: (kv[1].code or "", kv[0])
            )
        ]
        return self.async_show_form(
            step_id="platform",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_STOP_ID): SelectSelector(
                        SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST)
                    )
                }
            ),
            description_placeholders={"stop_name": self._stop_name or ""},
        )

    async def async_step_routes(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Výběr sledovaných linek (prázdný výběr = všechny)."""
        if user_input is not None:
            self._selected_routes = user_input.get(CONF_ROUTES, [])
            return await self.async_step_settings()
        return self.async_show_form(
            step_id="routes",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_ROUTES, default=[]): SelectSelector(
                        SelectSelectorConfig(
                            options=self._routes,
                            multiple=True,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Počet spojů, volitelný vlastní interval a název."""
        platform_code = self._platforms[self._stop_id].code
        default_title = (
            f"{self._stop_name} {platform_code}" if platform_code else self._stop_name
        )
        if user_input is not None:
            data: dict[str, Any] = {
                CONF_STOP_ID: self._stop_id,
                CONF_STOP_NAME: self._stop_name,
                CONF_PLATFORM: platform_code,
                CONF_ROUTES: list(self._selected_routes),
                CONF_LIMIT: int(user_input[CONF_LIMIT]),
            }
            if user_input.get(CONF_SCAN_INTERVAL):
                data[CONF_SCAN_INTERVAL] = int(user_input[CONF_SCAN_INTERVAL])
            return self.async_create_entry(
                title=user_input[CONF_NAME], data=data, unique_id=self._stop_id
            )
        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=default_title): TextSelector(),
                    vol.Required(CONF_LIMIT, default=DEFAULT_LIMIT): _limit_selector(),
                    vol.Optional(CONF_SCAN_INTERVAL): _interval_selector(),
                }
            ),
        )

    # ---- úprava ----

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Změna linek, limitu a intervalu (nástupiště se nemění)."""
        entry = self._get_entry()
        subentry = self._get_reconfigure_subentry()
        current = subentry.data

        if user_input is not None:
            data = {
                **current,
                CONF_ROUTES: list(user_input.get(CONF_ROUTES, [])),
                CONF_LIMIT: int(user_input[CONF_LIMIT]),
            }
            if user_input.get(CONF_SCAN_INTERVAL):
                data[CONF_SCAN_INTERVAL] = int(user_input[CONF_SCAN_INTERVAL])
            else:
                data.pop(CONF_SCAN_INTERVAL, None)
            return self.async_update_and_abort(entry, subentry, data=data)

        try:
            discovered = await self._discover([current[CONF_STOP_ID]])
        except GolemioError:
            discovered = {}
        routes = set(current.get(CONF_ROUTES) or [])
        for info in discovered.values():
            routes |= info.routes

        schema: dict[Any, Any] = {
            vol.Optional(
                CONF_ROUTES, default=list(current.get(CONF_ROUTES) or [])
            ): SelectSelector(
                SelectSelectorConfig(
                    options=sorted(routes, key=_route_sort_key),
                    multiple=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(CONF_LIMIT, default=current.get(CONF_LIMIT, DEFAULT_LIMIT)): _limit_selector(),
        }
        interval = current.get(CONF_SCAN_INTERVAL)
        schema[
            vol.Optional(CONF_SCAN_INTERVAL, description={"suggested_value": interval})
        ] = _interval_selector()
        return self.async_show_form(step_id="reconfigure", data_schema=vol.Schema(schema))
