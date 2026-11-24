"""Sensors."""

from __future__ import annotations

import time as _time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.util import dt as dt_util

from .entity import CulDeviceEntity, CulHubEntity, async_setup_device_platform
from .hub import DeviceState


def _warnings_text(v: int | None) -> str | None:
    if v is None:
        return None
    parts = []
    if v & 1:
        parts.append("Battery low")
    if v & 2:
        parts.append("Temperature too low")
    if v & 32:
        parts.append("Window open")
    if v & 16:
        parts.append("Fault on window sensor")
    return ", ".join(parts) or "none"


def _reliability(d: DeviceState) -> str | None:
    if d.last_seen is None:
        return None
    age = _time.time() - d.last_seen
    return "ok" if age < 300 else "medium" if age < 600 else "low" if age < 720 else "dead"


@dataclass(frozen=True, kw_only=True)
class CulSensorDescription(SensorEntityDescription):
    value_fn: Callable[[CulDeviceEntity], Any]


def _src(key: str) -> Callable[[CulDeviceEntity], Any]:
    return lambda e: e.dev_value(key)


def _last_seen(e: CulDeviceEntity):
    return dt_util.utc_from_timestamp(e.device.last_seen) if e.device.last_seen else None


LAST_SEEN = dict(key="last_seen", name="Last seen", device_class=SensorDeviceClass.TIMESTAMP,
                 entity_category=EntityCategory.DIAGNOSTIC, value_fn=_last_seen)
VALVE = [CulSensorDescription(key="actuator", name="Valve", native_unit_of_measurement=PERCENTAGE,
                              state_class=SensorStateClass.MEASUREMENT, value_fn=_src("actuator"))]
VALVE += [CulSensorDescription(key=f"actuator{i}", name=f"Valve {i}",
                               native_unit_of_measurement=PERCENTAGE,
                               state_class=SensorStateClass.MEASUREMENT,
                               entity_registry_enabled_default=False, value_fn=_src(f"actuator{i}"))
          for i in range(1, 9)]
DIAG_OFF = dict(entity_category=EntityCategory.DIAGNOSTIC, entity_registry_enabled_default=False)
FHT = (
    *VALVE,
    CulSensorDescription(**LAST_SEEN, entity_registry_enabled_default=False),
    CulSensorDescription(key="warnings", name="Warnings", value_fn=lambda e: _warnings_text(e.dev_value("warnings")), **DIAG_OFF),
    CulSensorDescription(key="can-xmit", name="Can transmit", value_fn=_src("can-xmit"), **DIAG_OFF),
    CulSensorDescription(key="can-rcv", name="Can receive", value_fn=_src("can-rcv"), **DIAG_OFF),
    CulSensorDescription(key="ack", name="Acknowledge", value_fn=_src("ack"), **DIAG_OFF),
)
FHTTK = (
    CulSensorDescription(**LAST_SEEN),
    CulSensorDescription(key="reliability", name="Reliability", device_class=SensorDeviceClass.ENUM,
                         options=["ok", "medium", "low", "dead"],
                         entity_category=EntityCategory.DIAGNOSTIC,
                         value_fn=lambda e: _reliability(e.device)),
)
DESCRIPTIONS = {"fht": FHT, "fhttk": FHTTK}
HUB_SENSORS = (
    ("fhtbuf", "FHT buffer", lambda s: s.fhtbuf),
    ("credit10ms", "Send credit", lambda s: s.credit10ms),
    ("version", "Firmware", lambda s: s.version),
    ("dropped", "Dropped telegrams", lambda s: s.dropped),
)


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    hub = entry.runtime_data
    async_add_entities([CulHubSensor(hub, key, name, fn) for key, name, fn in HUB_SENSORS])
    async_setup_device_platform(
        hass, entry, async_add_entities,
        lambda hub, d: [CulSensor(hub, d, desc) for desc in DESCRIPTIONS.get(d.protocol, ())],
    )


class CulSensor(CulDeviceEntity, SensorEntity):
    entity_description: CulSensorDescription

    def __init__(self, hub, device, description: CulSensorDescription) -> None:
        super().__init__(hub, device, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self)


class CulHubSensor(CulHubEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hub, key: str, name: str, fn) -> None:
        super().__init__(hub, key)
        self._attr_name = name
        self._fn = fn

    @property
    def native_value(self) -> Any:
        return self._fn(self.hub.cul.state)
