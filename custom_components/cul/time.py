"""FHT80b weekly schedule."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.const import EntityCategory

from .culpy.protocols.fht import SCHEDULE_KEYS
from .entity import CulDeviceEntity, async_setup_device_platform


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_setup_device_platform(
        hass, entry, async_add_entities,
        lambda hub, d: [FhtSchedule(hub, d, k) for k in SCHEDULE_KEYS] if d.protocol == "fht" else [],
    )


class FhtSchedule(CulDeviceEntity, TimeEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hub, device, key: str) -> None:
        super().__init__(hub, device, key)
        self._attr_name = key.replace("-", " ").capitalize()

    @property
    def native_value(self) -> time | None:
        return self.dev_value(self.key)

    @property
    def extra_state_attributes(self) -> dict[str, bool]:
        # "not used" (24:00) decodes to None, which looks like "never received"
        unused = (
            self.key in self.device.values
            and self.device.values[self.key] is None
            and not self.hub.is_pending(self.device.address, self.key)
        )
        return {"unused": unused}

    async def async_set_value(self, value: time) -> None:
        self.submit_values({self.key: time(value.hour, value.minute // 10 * 10)})
