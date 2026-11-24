"""FHT80b climate entity."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import voluptuous as vol
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.util import dt as dt_util

from .culpy.protocols.fht import holiday_items, refresh_items, time_items
from .entity import CulDeviceEntity, async_setup_device_platform

OFF_TEMP = 5.5
PRESETS = ["none", "holiday", "holiday_short"]


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    platform = entity_platform.async_get_current_platform()
    temp = vol.All(vol.Coerce(float), vol.Range(min=5.5, max=30.5))
    slot = vol.Any(None, "", cv.time)
    platform.async_register_entity_service("fht_set_holiday", {
        vol.Required("mode"): vol.In(["holiday", "holiday_short"]),
        vol.Required("end"): cv.datetime,
        vol.Required("temperature"): temp,
    }, "async_set_holiday")
    platform.async_register_entity_service("fht_set_schedule", {
        vol.Required("day"): vol.In(["mon", "tue", "wed", "thu", "fri", "sat", "sun"]),
        vol.Optional("from1"): slot, vol.Optional("to1"): slot,
        vol.Optional("from2"): slot, vol.Optional("to2"): slot,
    }, "async_set_schedule")
    platform.async_register_entity_service("fht_refresh", {}, "async_refresh")
    platform.async_register_entity_service("fht_sync_time", {}, "async_sync_time")
    platform.async_register_entity_service("fht_report", {
        vol.Optional("report1", default=255): vol.All(vol.Coerce(int), vol.Range(min=0, max=255)),
        vol.Optional("report2", default=255): vol.All(vol.Coerce(int), vol.Range(min=0, max=255)),
    }, "async_report")
    async_setup_device_platform(
        hass, entry, async_add_entities,
        lambda hub, d: [FhtClimate(hub, d)] if d.protocol == "fht" else [],
    )


class FhtClimate(CulDeviceEntity, ClimateEntity):
    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = 5.5
    _attr_max_temp = 30.5
    _attr_target_temperature_step = 0.5
    _attr_hvac_modes = [HVACMode.AUTO, HVACMode.HEAT, HVACMode.OFF]
    _attr_preset_modes = PRESETS
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, hub, device) -> None:
        super().__init__(hub, device, "climate")

    @property
    def current_temperature(self) -> float | None:
        return self.dev_value("measured-temp")

    @property
    def target_temperature(self) -> float | None:
        return self.dev_value("desired-temp")

    @property
    def hvac_mode(self) -> HVACMode | None:
        target, mode = self.dev_value("desired-temp"), self.dev_value("mode")
        if target is not None and target <= OFF_TEMP:
            return HVACMode.OFF
        if mode == "manual":
            return HVACMode.HEAT
        if mode in ("auto", "holiday", "holiday_short"):
            return HVACMode.AUTO
        return None

    @property
    def hvac_action(self) -> HVACAction | None:
        if self.hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        actuator = self.dev_value("actuator")
        if actuator is None:
            return None
        return HVACAction.HEATING if actuator > 0 else HVACAction.IDLE

    @property
    def preset_mode(self) -> str | None:
        mode = self.dev_value("mode")
        return mode if mode in ("holiday", "holiday_short") else "none"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"pending": sorted(k for (a, k) in self.hub.requested if a == self.device.address)}

    async def async_set_temperature(self, **kwargs: Any) -> None:
        values: dict[str, Any] = {}
        if (mode := kwargs.get("hvac_mode")) is not None:
            values.update(self._mode_values(mode))
        if (temp := kwargs.get(ATTR_TEMPERATURE)) is not None:
            values["desired-temp"] = float(temp)
        self.submit_values(values)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        self.submit_values(self._mode_values(hvac_mode))

    def _mode_values(self, hvac_mode: HVACMode) -> dict[str, Any]:
        if hvac_mode == HVACMode.OFF:
            return {"desired-temp": OFF_TEMP}
        values: dict[str, Any] = {"mode": "manual" if hvac_mode == HVACMode.HEAT else "auto"}
        target = self.dev_value("desired-temp")
        if target is None or target <= OFF_TEMP:
            values["desired-temp"] = self.dev_value("day-temp") or 20.0
        return values

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode == "none":
            self.submit_values(self._mode_values(HVACMode.AUTO))
            return
        raise ServiceValidationError("Use the cul.fht_set_holiday service to set holiday modes")

    async def async_set_holiday(self, mode: str, end, temperature: float) -> None:
        now = dt_util.now()
        end_local = dt_util.as_local(end) if end.tzinfo else end.replace(tzinfo=now.tzinfo)
        limit = timedelta(days=365 if mode == "holiday" else 28)
        if not now < end_local < now + limit:
            raise ServiceValidationError(
                f"End must be in the future and less than {limit.days} days ahead for {mode}")
        self.submit_values(dict(holiday_items(mode, end_local, temperature)))

    async def async_set_schedule(self, day: str, **slots) -> None:
        """Given fields are set ("" or null = unused); omitted fields keep the current value."""
        values: dict[str, Any] = {}
        final: dict[str, Any] = {}  # resulting slot values, where known
        for part in ("from1", "to1", "from2", "to2"):
            key = f"{day}-{part}"
            if part in slots:
                values[key] = final[part] = slots[part] or None
            elif key in self.device.values or self.hub.is_pending(self.device.address, key):
                final[part] = self.dev_value(key)
        for start, end in (("from1", "to1"), ("from2", "to2")):
            if start not in final or end not in final:
                continue  # other side unknown: nothing to check against
            if (final[start] is None) != (final[end] is None):
                raise ServiceValidationError(
                    f"{day} {start}/{end}: set both or neither (one side would be unused)")
            if final[start] is not None and final[start] > final[end]:
                raise ServiceValidationError(f"{day} {start} must not be after {end}")
        if values:
            self.submit_values(values)

    async def async_refresh(self) -> None:
        self.submit_values(dict(refresh_items()))

    async def async_sync_time(self) -> None:
        self.submit_values(dict(time_items(dt_util.now())))

    async def async_report(self, report1: int, report2: int) -> None:
        self.submit_values({"report1": report1, "report2": report2})
