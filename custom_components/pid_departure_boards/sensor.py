"""Sensor — nejbližší odjezd z nástupiště + seznam odjezdů v atributech."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_PLATFORM,
    CONF_STOP_ID,
    CONF_STOP_NAME,
    DOMAIN,
)
from .coordinator import PidConfigEntry, PlatformCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PidConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    for subentry_id, coordinator in entry.runtime_data.coordinators.items():
        async_add_entities(
            [DeparturesSensor(coordinator)], config_subentry_id=subentry_id
        )


class DeparturesSensor(CoordinatorEntity[PlatformCoordinator], SensorEntity):
    """Stav = čas nejbližšího odjezdu; atribut `departures` = všechny sledované spoje."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:bus-clock"
    # Velké a rychle se měnící atributy nepatří do historie
    _unrecorded_attributes = frozenset({"departures", "infotexts"})

    def __init__(self, coordinator: PlatformCoordinator) -> None:
        super().__init__(coordinator)
        subentry = coordinator.subentry
        self._attr_unique_id = subentry.subentry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            name=subentry.title,
            manufacturer="PID / Golemio",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> datetime | None:
        departures = self.coordinator.data.departures
        return departures[0].departure_time if departures else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        subentry_data = self.coordinator.subentry.data
        language = self.hass.config.language
        attributes: dict[str, Any] = {
            "stop_id": subentry_data[CONF_STOP_ID],
            "stop_name": subentry_data.get(CONF_STOP_NAME),
            "platform": subentry_data.get(CONF_PLATFORM),
            "departures": [d.as_dict() for d in data.departures],
            "infotexts": [i.as_dict(language) for i in data.infotexts],
        }
        # `latitude`/`longitude` způsobí, že se nástupiště zobrazí na mapě
        if (lat := subentry_data.get(CONF_LATITUDE)) is not None and (
            lon := subentry_data.get(CONF_LONGITUDE)
        ) is not None:
            attributes["latitude"] = lat
            attributes["longitude"] = lon
        return attributes
