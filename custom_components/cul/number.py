"""FHT80b temperature settings."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfTemperature

from .entity import CulDeviceEntity, async_setup_device_platform

TEMPS = {
    "day-temp": "Day temperature",
    "night-temp": "Night temperature",
    "windowopen-temp": "Window open temperature",
    "manu-temp": "Manual temperature",
}


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    def factory(hub, d):
        if d.protocol != "fht":
            return []
        return [FhtTemperature(hub, d, k, n) for k, n in TEMPS.items()] + [FhtLowtempOffset(hub, d)]

    async_setup_device_platform(hass, entry, async_add_entities, factory)


class FhtTemperature(CulDeviceEntity, NumberEntity):
    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = 5.5
    _attr_native_max_value = 30.5
    _attr_native_step = 0.5
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hub, device, key: str, name: str) -> None:
        super().__init__(hub, device, key)
        self._attr_name = name

    @property
    def native_value(self) -> float | None:
        return self.dev_value(self.key)

    async def async_set_native_value(self, value: float) -> None:
        self.submit_values({self.key: value})


class FhtLowtempOffset(CulDeviceEntity, NumberEntity):
    _attr_name = "Low temperature offset"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = 1
    _attr_native_max_value = 5
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hub, device) -> None:
        super().__init__(hub, device, "lowtemp-offset")

    @property
    def native_value(self) -> int | None:
        return self.dev_value("lowtemp-offset")

    async def async_set_native_value(self, value: float) -> None:
        self.submit_values({"lowtemp-offset": int(value)})
