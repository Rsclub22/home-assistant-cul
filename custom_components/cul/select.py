"""FHT80b mode."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.exceptions import ServiceValidationError

from .entity import CulDeviceEntity, async_setup_device_platform

OPTIONS = ["auto", "manual", "holiday", "holiday_short"]


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_setup_device_platform(
        hass, entry, async_add_entities,
        lambda hub, d: [FhtMode(hub, d)] if d.protocol == "fht" else [],
    )


class FhtMode(CulDeviceEntity, SelectEntity):
    _attr_name = "Mode"
    _attr_options = OPTIONS

    def __init__(self, hub, device) -> None:
        super().__init__(hub, device, "mode")

    @property
    def current_option(self) -> str | None:
        mode = self.dev_value("mode")
        return mode if mode in OPTIONS else None

    async def async_select_option(self, option: str) -> None:
        if option in ("holiday", "holiday_short"):
            raise ServiceValidationError("Use the cul.fht_set_holiday service for holiday modes")
        self.submit_values({"mode": option})
