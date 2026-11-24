"""Binary sensors."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory

from .entity import CulDeviceEntity, CulHubEntity, async_setup_device_platform


@dataclass(frozen=True, kw_only=True)
class CulBinaryDescription(BinarySensorEntityDescription):
    source: str


FHT = (
    CulBinaryDescription(key="window", source="window-open", name="Window",
                         device_class=BinarySensorDeviceClass.WINDOW),
    CulBinaryDescription(key="battery", source="battery-low", name="Battery",
                         device_class=BinarySensorDeviceClass.BATTERY),
    CulBinaryDescription(key="lowtemp", source="lowtemp", name="Low temperature",
                         device_class=BinarySensorDeviceClass.COLD),
    CulBinaryDescription(key="windowsensor", source="windowsensor-fault", name="Window sensor fault",
                         device_class=BinarySensorDeviceClass.PROBLEM),
)
FHTTK = FHT[:2]
DESCRIPTIONS = {"fht": FHT, "fhttk": FHTTK}


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    hub = entry.runtime_data
    async_add_entities([CulConnection(hub, "connected")])
    async_setup_device_platform(
        hass, entry, async_add_entities,
        lambda hub, d: [CulBinarySensor(hub, d, desc) for desc in DESCRIPTIONS.get(d.protocol, ())],
    )


class CulBinarySensor(CulDeviceEntity, BinarySensorEntity):
    entity_description: CulBinaryDescription

    def __init__(self, hub, device, description: CulBinaryDescription) -> None:
        super().__init__(hub, device, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.dev_value(self.entity_description.source)


class CulConnection(CulHubEntity, BinarySensorEntity):
    _attr_name = "Connection"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool:
        return self.hub.cul.state.connected
