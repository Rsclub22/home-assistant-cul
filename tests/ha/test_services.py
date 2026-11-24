"""Service tests."""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
import voluptuous as vol
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.cul.culpy.transport.fake import FakeTransport

from .helpers import ANSWERS, rf, settle, setup_cul, written

ENTITY = "climate.fht_1c50"


async def setup(hass, **kwargs):
    fake = FakeTransport(ANSWERS)
    entry = await setup_cul(hass, fake, **kwargs)
    fake.feed(rf("1C50416928"))
    await settle(hass)
    fake.written.clear()
    return fake, entry


async def test_set_holiday(hass):
    fake, entry = await setup(hass)
    await hass.services.async_call("cul", "fht_set_holiday", {
        "entity_id": ENTITY, "mode": "holiday", "end": "2026-12-24 00:00:00", "temperature": 15.0,
    }, blocking=True)
    await settle(hass)
    assert written(fake) == ["T1C50411E3E023F18400C"]
    await hass.config_entries.async_unload(entry.entry_id)


async def test_set_schedule(hass):
    fake, entry = await setup(hass)
    await hass.services.async_call("cul", "fht_set_schedule", {
        "entity_id": ENTITY, "day": "mon", "from1": "06:00", "to1": "08:00",
    }, blocking=True)
    await settle(hass)
    # from2/to2 omitted and not known: not sent (never cleared)
    assert written(fake) == ["T1C5014241530"]
    await hass.config_entries.async_unload(entry.entry_id)


async def test_refresh_and_report(hass):
    fake, entry = await setup(hass)
    await hass.services.async_call("cul", "fht_refresh", {"entity_id": ENTITY}, blocking=True)
    await settle(hass)
    assert written(fake) == ["T1C5065FF66FF"]
    await hass.config_entries.async_unload(entry.entry_id)


async def test_send_raw(hass):
    fake, entry = await setup(hass)
    await hass.services.async_call("cul", "send_raw", {"line": "V"}, blocking=True)
    assert fake.written[-1] == "V"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_send_raw_unknown_entry(hass):
    fake, entry = await setup(hass)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "cul", "send_raw", {"line": "V", "config_entry_id": "nope"}, blocking=True)
    await hass.config_entries.async_unload(entry.entry_id)


async def test_send_raw_no_cul(hass):
    fake, entry = await setup(hass)
    await hass.config_entries.async_unload(entry.entry_id)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("cul", "send_raw", {"line": "V"}, blocking=True)


@pytest.mark.parametrize("line", ["V\nX99", "V\rX99", "", "   ", "\n", "Ä", "V\x00"])
async def test_send_raw_rejects_bad_line(hass, line):
    fake, entry = await setup(hass)
    with pytest.raises((vol.Invalid, ServiceValidationError)):
        await hass.services.async_call("cul", "send_raw", {"line": line}, blocking=True)
    assert fake.written == []
    await hass.config_entries.async_unload(entry.entry_id)


async def test_send_raw_strips(hass):
    fake, entry = await setup(hass)
    await hass.services.async_call("cul", "send_raw", {"line": " V "}, blocking=True)
    assert fake.written[-1] == "V"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_entity_write_value_error_is_validation_error(hass):
    fake, entry = await setup(hass)
    entity = hass.data["climate"].get_entity(ENTITY)
    with pytest.raises(ServiceValidationError):
        await entity.async_set_temperature(temperature=40.0)
    await settle(hass)
    assert written(fake) == []
    await hass.config_entries.async_unload(entry.entry_id)


NOW = datetime.fromisoformat("2026-11-21T12:00:00+01:00")


async def call_holiday(hass, mode, end):
    await hass.services.async_call("cul", "fht_set_holiday", {
        "entity_id": ENTITY, "mode": mode, "end": end, "temperature": 15.0}, blocking=True)


@pytest.mark.parametrize(("mode", "end"), [
    ("holiday", "2026-11-20 10:00:00"),         # past
    ("holiday_short", "2026-11-21 11:00:00"),   # past
    ("holiday", "2027-12-26 00:00:00"),         # > 365 days
    ("holiday_short", "2026-12-21 12:00:01"),   # > 28 days
])
async def test_holiday_end_out_of_range(hass, mode, end):
    await hass.config.async_set_time_zone("Europe/Berlin")
    fake, entry = await setup(hass)
    with patch.object(dt_util, "now", return_value=NOW), pytest.raises(ServiceValidationError):
        await call_holiday(hass, mode, end)
    await settle(hass)
    assert written(fake) == []
    await hass.config_entries.async_unload(entry.entry_id)


async def test_holiday_short(hass):
    await hass.config.async_set_time_zone("Europe/Berlin")
    fake, entry = await setup(hass)
    with patch.object(dt_util, "now", return_value=NOW):
        await call_holiday(hass, "holiday_short", "2026-11-22 06:30:00")
    await settle(hass)
    assert written(fake) == ["T1C50411E3E033F274016"]
    await hass.config_entries.async_unload(entry.entry_id)


async def test_report(hass):
    fake, entry = await setup(hass)
    await hass.services.async_call(
        "cul", "fht_report", {"entity_id": ENTITY, "report1": 1, "report2": 2}, blocking=True)
    await settle(hass)
    assert written(fake) == ["T1C5065016602"]
    await hass.config_entries.async_unload(entry.entry_id)


async def test_sync_time_service(hass):
    await hass.config.async_set_time_zone("Europe/Berlin")
    fake, entry = await setup(hass)
    with patch.object(dt_util, "now", return_value=datetime.fromisoformat("2026-11-21T04:00:00+01:00")):
        await hass.services.async_call("cul", "fht_sync_time", {"entity_id": ENTITY}, blocking=True)
    await settle(hass)
    assert written(fake) == ["T1C506400601A610B62156304"]
    await hass.config_entries.async_unload(entry.entry_id)


async def test_set_schedule_empty_string_is_unused(hass):
    fake, entry = await setup(hass)
    await hass.services.async_call("cul", "fht_set_schedule", {
        "entity_id": ENTITY, "day": "mon", "from1": "06:00", "to1": "08:00",
        "from2": "", "to2": "",
    }, blocking=True)
    await settle(hass)
    assert written(fake) == ["T1C501424153016901790"]
    await hass.config_entries.async_unload(entry.entry_id)


# freezer + settle hangs the loop clock, so no freezing: the 04:00:00 time-change
# listener is fired at the next real 04:00 Berlin (UTC instant, as HA schedules it)
# while dt_util.now returns 2026-11-21 04:00 Berlin, the time the FHT clock must get.
BERLIN_4 = "2026-11-21T04:00:00+01:00"


async def fire_four_am(hass):
    local_now = dt_util.now()
    next_four = local_now.replace(hour=4, minute=0, second=0, microsecond=0)
    if next_four <= local_now:
        next_four += timedelta(days=1)
    with patch.object(dt_util, "now", return_value=datetime.fromisoformat(BERLIN_4)):
        async_fire_time_changed(hass, dt_util.as_utc(next_four))
        await settle(hass)


async def test_daily_time_sync(hass):
    await hass.config.async_set_time_zone("Europe/Berlin")
    fake, entry = await setup(hass)
    entry.runtime_data.ensure_device("fht", "0e52")  # silent device: no time sync
    await fire_four_am(hass)
    assert written(fake) == ["T1C506400601A610B62156304"]
    assert entry.runtime_data.queue.pending_for("0e52") == {}
    await hass.config_entries.async_unload(entry.entry_id)


async def test_no_time_sync_when_disabled(hass):
    await hass.config.async_set_time_zone("Europe/Berlin")
    fake, entry = await setup(hass, options={"time_sync": False})
    await fire_four_am(hass)
    assert written(fake) == []
    await hass.config_entries.async_unload(entry.entry_id)


async def test_send_raw_admin_only(hass, hass_read_only_user):
    from homeassistant.core import Context
    from homeassistant.exceptions import Unauthorized

    fake, entry = await setup(hass)
    with pytest.raises(Unauthorized):
        await hass.services.async_call("cul", "send_raw", {"line": "X00"}, blocking=True,
                                       context=Context(user_id=hass_read_only_user.id))
    assert fake.written == []
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("line", ["T011234", "t011234", " T010000"])
async def test_send_raw_t01_needs_confirm(hass, line):
    fake, entry = await setup(hass)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call("cul", "send_raw", {"line": line}, blocking=True)
    assert fake.written == []
    await hass.services.async_call("cul", "send_raw", {"line": line, "confirm": True}, blocking=True)
    assert fake.written == [line.strip()]
    await hass.config_entries.async_unload(entry.entry_id)


async def feed_schedule(hass, fake, **slots):
    codes = {"from1": 0x14, "to1": 0x15, "from2": 0x16, "to2": 0x17}  # monday
    for part, val in slots.items():
        fake.feed(rf(f"1C50{codes[part]:02X}69{val:02X}"))
    await settle(hass)
    fake.written.clear()


async def test_set_schedule_omitted_keeps_current(hass):
    fake, entry = await setup(hass)
    await feed_schedule(hass, fake, from1=0x24, to1=0x30, from2=0x6C, to2=0x84)  # 6-8, 18-22
    await hass.services.async_call("cul", "fht_set_schedule", {
        "entity_id": ENTITY, "day": "mon", "from1": "07:00"}, blocking=True)
    await settle(hass)
    assert written(fake) == ["T1C50142A"]
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("data", [
    {"from1": "09:00", "to1": "08:00"},          # from after to
    {"from1": "09:00"},                          # after the known to1 08:00
    {"from1": "06:00", "to1": ""},               # one side unused
    {"from2": "06:00"},                          # known to2 is unused
])
async def test_set_schedule_invalid_pair(hass, data):
    fake, entry = await setup(hass)
    await feed_schedule(hass, fake, from1=0x24, to1=0x30, from2=0x90, to2=0x90)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call("cul", "fht_set_schedule", {
            "entity_id": ENTITY, "day": "mon", **data}, blocking=True)
    await settle(hass)
    assert written(fake) == []
    await hass.config_entries.async_unload(entry.entry_id)
