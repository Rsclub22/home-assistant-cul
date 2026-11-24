"""Climate tests."""

from datetime import timedelta

import pytest
from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ATTR_PRESET_MODE,
    HVACAction,
    HVACMode,
)
from homeassistant.components.climate import (
    DOMAIN as CLIMATE,
)
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.cul.culpy.transport.fake import FakeTransport

from .helpers import ANSWERS, rf, settle, setup_cul, written

ENTITY = "climate.fht_1c50"


async def setup_fht(hass):
    fake = FakeTransport(ANSWERS)
    entry = await setup_cul(hass, fake)
    for p in ["1C50416928", "1C504269C4", "1C50436900", "1C503E6900", "1C50002633"]:
        fake.feed(rf(p))
    await settle(hass)
    return fake, entry


async def test_state(hass):
    fake, entry = await setup_fht(hass)
    state = hass.states.get(ENTITY)
    assert state.state == HVACMode.AUTO
    assert state.attributes["temperature"] == 20.0
    assert state.attributes["current_temperature"] == 19.6
    assert state.attributes["hvac_action"] == HVACAction.HEATING
    assert state.attributes["min_temp"] == 5.5
    assert state.attributes["max_temp"] == 30.5
    await hass.config_entries.async_unload(entry.entry_id)


async def test_set_temperature_pending_then_confirmed(hass):
    fake, entry = await setup_fht(hass)
    await hass.services.async_call(CLIMATE, "set_temperature",
                                   {ATTR_ENTITY_ID: ENTITY, ATTR_TEMPERATURE: 21.0}, blocking=True)
    await settle(hass)
    assert "T1C50412A" in written(fake)
    state = hass.states.get(ENTITY)
    assert state.attributes["temperature"] == 21.0
    assert state.attributes["pending"] == ["desired-temp"]
    fake.feed(rf("1C5041692A"))
    await settle(hass)
    assert hass.states.get(ENTITY).attributes["pending"] == []
    await hass.config_entries.async_unload(entry.entry_id)


async def test_hvac_modes(hass):
    fake, entry = await setup_fht(hass)
    for mode, line in [(HVACMode.HEAT, "T1C503E01"), (HVACMode.OFF, "T1C50410B"),
                       (HVACMode.AUTO, "T1C5041283E00")]:
        await hass.services.async_call(CLIMATE, "set_hvac_mode",
                                       {ATTR_ENTITY_ID: ENTITY, ATTR_HVAC_MODE: mode}, blocking=True)
        await settle(hass)
        assert line in written(fake)
    await hass.config_entries.async_unload(entry.entry_id)


async def test_preset_holiday_needs_service(hass):
    fake, entry = await setup_fht(hass)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(CLIMATE, "set_preset_mode",
                                       {ATTR_ENTITY_ID: ENTITY, ATTR_PRESET_MODE: "holiday"},
                                       blocking=True)
    await hass.config_entries.async_unload(entry.entry_id)


async def test_unavailable_without_telegram(hass):
    # The freezer fixture also freezes the event loop clock, which hangs
    # settle() (asyncio.sleep); age the last telegram and fire the hub tick instead.
    fake, entry = await setup_fht(hass)
    entry.runtime_data.devices["fht:1c50"].last_seen -= 7201
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await settle(hass)
    assert hass.states.get(ENTITY).state == "unavailable"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_auto_from_off_restores_target(hass):
    fake, entry = await setup_fht(hass)
    for p in ["1C50826928", "1C5041690B"]:
        fake.feed(rf(p))
    await settle(hass)
    assert hass.states.get(ENTITY).state == HVACMode.OFF
    fake.written.clear()
    await hass.services.async_call(
        CLIMATE, "set_hvac_mode", {ATTR_ENTITY_ID: ENTITY, ATTR_HVAC_MODE: HVACMode.AUTO}, blocking=True
    )
    await settle(hass)
    sent = written(fake)
    assert sent == ["T1C5041283E00"]  # desired-temp 20.0 and mode auto in one telegram
    assert hass.states.get(ENTITY).state == HVACMode.AUTO
    await hass.config_entries.async_unload(entry.entry_id)


async def test_preset_none_from_off_restores_target(hass):
    fake, entry = await setup_fht(hass)
    for p in ["1C50826928", "1C5041690B"]:
        fake.feed(rf(p))
    await settle(hass)
    fake.written.clear()
    await hass.services.async_call(
        CLIMATE, "set_preset_mode", {ATTR_ENTITY_ID: ENTITY, ATTR_PRESET_MODE: "none"}, blocking=True
    )
    await settle(hass)
    sent = written(fake)
    assert sent == ["T1C5041283E00"]  # desired-temp 20.0 and mode auto in one telegram
    assert hass.states.get(ENTITY).state == HVACMode.AUTO
    await hass.config_entries.async_unload(entry.entry_id)
