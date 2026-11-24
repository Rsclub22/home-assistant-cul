"""Base entities."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, signal_cul, signal_new, signal_update
from .hub import CulHub, DeviceState

MODELS = {"fht": "FHT80b", "fhttk": "FHT80TF"}
NAMES = {"fht": "FHT", "fhttk": "FHT80TF"}


class CulDeviceEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub: CulHub, device: DeviceState, key: str) -> None:
        self.hub, self.device, self.key = hub, device, key
        uid = hub.entry.unique_id
        cul_device = dr.async_get(hub.hass).async_get_device_by_identifier(
            (DOMAIN, f"cul:{uid}"), hub.entry.entry_id
        )
        self._attr_unique_id = f"{uid}_{device.protocol}_{device.address}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.key)},
            name=f"{NAMES[device.protocol]} {device.address}",
            manufacturer="ELV",
            model=MODELS[device.protocol],
            via_device_id=cul_device.id if cul_device else None,
        )

    def submit_values(self, values: dict[str, Any]) -> None:
        """Queue values for this device; invalid values become a validation error."""
        try:
            self.hub.submit(self.device.address, values)
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err

    @property
    def available(self) -> bool:
        return self.hub.is_available(self.device)

    def dev_value(self, key: str) -> Any:
        return self.hub.display_value(self.device, key)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(
            self.hass, signal_update(self.hub.entry.entry_id, self.device.key), self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


class CulHubEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub: CulHub, key: str) -> None:
        self.hub, self.key = hub, key
        uid = hub.entry.unique_id
        self._attr_unique_id = f"{uid}_cul_{key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, f"cul:{uid}")})

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(
            self.hass, signal_cul(self.hub.entry.entry_id), self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


def async_setup_device_platform(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
    factory: Callable[[CulHub, DeviceState], list[Entity]],
) -> None:
    hub: CulHub = entry.runtime_data

    @callback
    def add(device: DeviceState) -> None:
        entities = factory(hub, device)
        if entities:
            async_add_entities(entities)

    for device in list(hub.devices.values()):
        add(device)
    entry.async_on_unload(async_dispatcher_connect(hass, signal_new(entry.entry_id), add))
