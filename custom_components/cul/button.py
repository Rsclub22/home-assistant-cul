"""Button: restart the CUL."""

from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError

from .entity import CulHubEntity


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities([CulRestartButton(entry.runtime_data, "restart")])


class CulRestartButton(CulHubEntity, ButtonEntity):
    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.CONFIG
    _attr_name = "Restart"

    async def async_press(self) -> None:
        try:
            await self.hub.async_restart_cul()
        except (ConnectionError, OSError) as err:
            raise HomeAssistantError(f"CUL not reachable: {err}") from err
