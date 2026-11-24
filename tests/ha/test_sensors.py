"""Sensor and binary_sensor tests."""

from custom_components.cul.culpy.transport.fake import FakeTransport

from .helpers import ANSWERS, rf, settle, setup_cul


async def test_fht_sensors(hass):
    fake = FakeTransport(ANSWERS)
    entry = await setup_cul(hass, fake)
    fake.feed(rf("1C50446921"))
    fake.feed(rf("1C50002633"))
    await settle(hass)
    assert hass.states.get("binary_sensor.fht_1c50_window").state == "on"
    assert hass.states.get("binary_sensor.fht_1c50_battery").state == "on"
    assert hass.states.get("binary_sensor.fht_1c50_low_temperature").state == "off"
    assert hass.states.get("sensor.fht_1c50_valve").state == "20"
    assert hass.states.get("sensor.fht_1c50_valve_1") is None  # disabled by default
    await hass.config_entries.async_unload(entry.entry_id)


async def test_fhttk_sensors(hass):
    fake = FakeTransport(ANSWERS)
    entry = await setup_cul(hass, fake)
    fake.feed(rf("B1987B91"))
    await settle(hass)
    assert hass.states.get("binary_sensor.fht80tf_b1987b_window").state == "on"
    assert hass.states.get("binary_sensor.fht80tf_b1987b_battery").state == "on"
    assert hass.states.get("sensor.fht80tf_b1987b_last_seen").state not in ("unknown", "unavailable")
    await hass.config_entries.async_unload(entry.entry_id)


async def test_cul_connection(hass):
    fake = FakeTransport(ANSWERS)
    entry = await setup_cul(hass, fake)
    assert hass.states.get("binary_sensor.cul_1034_connection").state == "on"
    fake.answers.clear()
    fake.drop()
    await settle(hass)
    assert hass.states.get("binary_sensor.cul_1034_connection").state == "off"
    await hass.config_entries.async_unload(entry.entry_id)
