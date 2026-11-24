"""number/select/time tests."""

import pytest
from homeassistant.exceptions import ServiceValidationError

from custom_components.cul.culpy.transport.fake import FakeTransport

from .helpers import ANSWERS, rf, settle, setup_cul, written


async def setup(hass):
    fake = FakeTransport(ANSWERS)
    entry = await setup_cul(hass, fake)
    for p in ["1C50826928", "1C503E6900", "1C50146924"]:
        fake.feed(rf(p))
    await settle(hass)
    return fake, entry


async def test_values(hass):
    fake, entry = await setup(hass)
    assert hass.states.get("number.fht_1c50_day_temperature").state == "20.0"
    assert hass.states.get("select.fht_1c50_mode").state == "auto"
    assert hass.states.get("time.fht_1c50_mon_from1").state == "06:00:00"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_set_values(hass):
    fake, entry = await setup(hass)
    await hass.services.async_call("number", "set_value",
        {"entity_id": "number.fht_1c50_day_temperature", "value": 21.5}, blocking=True)
    await hass.services.async_call("select", "select_option",
        {"entity_id": "select.fht_1c50_mode", "option": "manual"}, blocking=True)
    await hass.services.async_call("time", "set_value",
        {"entity_id": "time.fht_1c50_mon_from1", "time": "06:35:00"}, blocking=True)
    await settle(hass)
    sent = written(fake)
    for line in ("T1C50822B", "T1C503E011427"):
        assert line in sent
    await hass.config_entries.async_unload(entry.entry_id)


async def test_select_holiday_needs_service(hass):
    fake, entry = await setup(hass)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call("select", "select_option",
            {"entity_id": "select.fht_1c50_mode", "option": "holiday"}, blocking=True)
    await hass.config_entries.async_unload(entry.entry_id)


async def test_schedule_unused_attribute(hass):
    fake, entry = await setup(hass)
    state = hass.states.get("time.fht_1c50_mon_from1")
    assert state.state == "06:00:00"
    assert state.attributes["unused"] is False
    fake.feed(rf("1C50146990"))
    await settle(hass)
    state = hass.states.get("time.fht_1c50_mon_from1")
    assert state.state == "unknown"
    assert state.attributes["unused"] is True
    await hass.config_entries.async_unload(entry.entry_id)
