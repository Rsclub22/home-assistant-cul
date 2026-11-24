"""Hub tests: events, autocreate, storage, pending values."""

import asyncio
from unittest.mock import patch

from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.cul.const import EVENT_COMMAND_FAILED
from custom_components.cul.culpy.transport.fake import FakeTransport

from .helpers import ANSWERS, rf, settle, setup_cul, written


async def test_event_creates_device(hass):
    fake = FakeTransport(ANSWERS)
    entry = await setup_cul(hass, fake)
    hub = entry.runtime_data
    fake.feed(rf("1C50416928"))
    fake.feed(rf("B1987B02"))
    await settle(hass)
    assert hub.devices["fht:1c50"].values["desired-temp"] == 20.0
    assert hub.devices["fhttk:b1987b"].values["window-open"] is False
    assert hub.devices["fht:1c50"].last_seen is not None
    await hass.config_entries.async_unload(entry.entry_id)


async def test_submit_sends_and_confirms(hass):
    fake = FakeTransport(ANSWERS)
    entry = await setup_cul(hass, fake)
    hub = entry.runtime_data
    fake.feed(rf("1C50416928"))  # only devices heard recently get commands
    await settle(hass)
    hub.submit("1c50", {"desired-temp": 21.0})
    await settle(hass)
    assert written(fake) == ["T1C50412A"]
    assert hub.is_pending("1c50", "desired-temp")
    assert hub.display_value(hub.devices["fht:1c50"], "desired-temp") == 21.0
    fake.feed(rf("1C5041692A"))
    await settle(hass)
    assert not hub.is_pending("1c50", "desired-temp")
    await hass.config_entries.async_unload(entry.entry_id)


async def test_restart_keeps_confirmed_values(hass):
    fake = FakeTransport(ANSWERS)
    entry = await setup_cul(hass, fake)
    hub = entry.runtime_data
    fake.feed(rf("1C50416928"))
    await settle(hass)
    hub.submit("1c50", {"desired-temp": 25.0})
    await settle(hass)
    with patch("custom_components.cul.hub.create_transport", return_value=FakeTransport(ANSWERS)):
        assert await hass.config_entries.async_reload(entry.entry_id)
        await settle(hass)
    hub = entry.runtime_data
    device = hub.devices["fht:1c50"]
    assert hub.display_value(device, "desired-temp") == 20.0
    assert not hub.is_pending("1c50", "desired-temp")
    await hass.config_entries.async_unload(entry.entry_id)


async def test_concurrent_pumps_send_each_telegram_once(hass):
    fake = FakeTransport(ANSWERS)
    entry = await setup_cul(hass, fake)
    hub = entry.runtime_data
    fake.feed(rf("1C50416928"))
    fake.feed(rf("2C50416928"))
    await settle(hass)
    hub.submit("1c50", {"desired-temp": 21.0})
    hub.submit("2c50", {"desired-temp": 21.0})
    await asyncio.gather(hub._async_pump_tick(None), hub._async_pump_tick(None))
    await settle(hass)
    assert sorted(written(fake)) == ["T1C50412A", "T2C50412A"]
    await hass.config_entries.async_unload(entry.entry_id)


async def test_command_failed_event_has_requested_value(hass):
    fake = FakeTransport(ANSWERS)
    entry = await setup_cul(hass, fake)
    hub = entry.runtime_data
    now = [1000.0]
    # FhtSendQueue binds time.monotonic at definition time, so freezer cannot move it
    hub.queue._clock = lambda: now[0]
    events = async_capture_events(hass, EVENT_COMMAND_FAILED)
    hub.submit("1c50", {"desired-temp": 21.0})
    await settle(hass)
    assert hub.is_pending("1c50", "desired-temp")
    now[0] += 901
    await hub._async_pump_tick(None)
    await settle(hass)
    assert [e.data for e in events] == [{"address": "1c50", "key": "desired-temp", "value": 21.0}]
    assert not hub.is_pending("1c50", "desired-temp")
    await hass.config_entries.async_unload(entry.entry_id)


async def test_unavailable_device_waits_available_is_sent(hass):
    fake = FakeTransport(ANSWERS)
    entry = await setup_cul(hass, fake)
    hub = entry.runtime_data
    hub.ensure_device("fht", "0e52")  # known from the registry, never heard
    fake.feed(rf("1C50416928"))
    await settle(hass)
    hub.submit("0e52", {"desired-temp": 21.0})
    hub.submit("1c50", {"desired-temp": 21.0})
    await settle(hass)
    assert written(fake) == ["T1C50412A"]
    assert hub.is_pending("0e52", "desired-temp")
    assert hub.queue.pending_for("0e52") == {"desired-temp": 42}
    await hass.config_entries.async_unload(entry.entry_id)


async def test_unknown_only_event_creates_no_device(hass):
    fake = FakeTransport(ANSWERS)
    entry = await setup_cul(hass, fake)
    hub = entry.runtime_data
    fake.feed(rf("ABCD7F6900"))  # unknown FHT code from an unknown address
    fake.feed("T1C50002633")  # truncated FHT frame, would read as FHT80TF 1c5000
    await settle(hass)
    assert set(hub.devices) == set()
    await hass.config_entries.async_unload(entry.entry_id)


async def test_remove_stray_device(hass):
    from homeassistant.helpers import device_registry as dr

    from custom_components.cul import async_remove_config_entry_device

    fake = FakeTransport(ANSWERS)
    entry = await setup_cul(hass, fake)
    hub = entry.runtime_data
    fake.feed(rf("B1987B02"))
    await settle(hass)
    dev_reg = dr.async_get(hass)
    stray = dev_reg.async_get_device_by_identifier(("cul", "fhttk:b1987b"), entry.entry_id)
    cul_dev = dev_reg.async_get_device_by_identifier(("cul", "cul:1034"), entry.entry_id)
    assert await async_remove_config_entry_device(hass, entry, cul_dev) is False
    assert await async_remove_config_entry_device(hass, entry, stray) is True
    assert "fhttk:b1987b" not in hub.devices
    await hass.config_entries.async_unload(entry.entry_id)
