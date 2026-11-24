"""FHT80b pairing: sends to a never heard FHT until it answers."""

from unittest.mock import patch

import pytest
import voluptuous as vol
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.cul import fht_code
from custom_components.cul.const import (
    EVENT_FHT_PAIR_FAILED,
    EVENT_FHT_PAIRED,
)
from custom_components.cul.culpy.transport.fake import FakeTransport
from custom_components.cul.hub import fht_code_display

from .helpers import ANSWERS, rf, settle, setup_cul, written

REPORT = "T1C5065FF66FF"


def test_fht_code():
    assert fht_code("028 080") == "1c50"
    assert fht_code("28 80") == "1c50"
    assert fht_code(" 1C50 ") == "1c50"
    assert fht_code("5 5") == "0505"
    assert fht_code_display("1c50") == "028 080"
    for bad in ("2880x", "123 4", "100 001", "1c5"):
        with pytest.raises(vol.Invalid):
            fht_code(bad)


async def notifications(hass):
    from homeassistant.components.persistent_notification import _async_get_or_create_notifications

    return _async_get_or_create_notifications(hass)


async def test_pair_until_answer(hass):
    fake = FakeTransport(ANSWERS)
    entry = await setup_cul(hass, fake)
    hub = entry.runtime_data
    paired = async_capture_events(hass, EVENT_FHT_PAIRED)
    await hass.services.async_call("cul", "fht_pair", {"code": "028 080"}, blocking=True)
    await settle(hass)
    assert "fht:1c50" in hub.devices  # entities exist (unavailable) right away
    assert written(fake) == [REPORT]  # sent although never heard
    fake.written.clear()

    # no resend: culfw holds the command until the FHT picks it up
    with patch("custom_components.cul.hub._time.time", return_value=hub._pairing["1c50"] - 1):
        hub._async_pair_tick()
    await settle(hass)
    assert written(fake) == []

    fake.feed(rf("1C5000A624"))  # actuator telegram: an FHT in CEnt nA keeps sending it
    await settle(hass)
    assert hub.is_pairing("1c50") and paired == []

    fake.feed("T1C506569FFFC")  # FHT confirms report1: it accepted the CUL as central
    await settle(hass)
    assert not hub.is_pairing("1c50")
    assert [e.data for e in paired] == [{"address": "1c50"}]
    assert "cul_pair_1c50" in await notifications(hass)
    assert written(fake)[0].startswith("T1C50")  # clock is set after pairing
    await hass.config_entries.async_unload(entry.entry_id)


async def test_pair_timeout(hass):
    fake = FakeTransport(ANSWERS)
    entry = await setup_cul(hass, fake)
    hub = entry.runtime_data
    failed = async_capture_events(hass, EVENT_FHT_PAIR_FAILED)
    await hass.services.async_call("cul", "fht_pair", {"code": "1c50"}, blocking=True)
    deadline = hub._pairing["1c50"]
    with patch("custom_components.cul.hub._time.time", return_value=deadline):
        hub._async_pair_tick()
    await settle(hass)
    assert not hub.is_pairing("1c50")
    assert [e.data for e in failed] == [{"address": "1c50"}]
    # silent again: no more commands to this FHT
    fake.written.clear()
    hub.submit("1c50", {"report1": 255})
    await settle(hass)
    assert written(fake) == []
    await hass.config_entries.async_unload(entry.entry_id)


async def test_pair_needs_choice_with_two_culs(hass):
    first = await setup_cul(hass, FakeTransport(ANSWERS))
    second = await setup_cul(hass, FakeTransport({**ANSWERS, "T01": "0E52"}),
                             data={"fhtid": "0E52", "host": "other"}, unique_id="0E52")
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call("cul", "fht_pair", {"code": "1c50"}, blocking=True)
    await hass.services.async_call(
        "cul", "fht_pair", {"code": "1c50", "config_entry_id": second.entry_id}, blocking=True)
    assert second.runtime_data.is_pairing("1c50")
    assert not first.runtime_data.is_pairing("1c50")
    for entry in (first, second):
        await hass.config_entries.async_unload(entry.entry_id)


async def test_pair_options_flow(hass):
    from homeassistant.data_entry_flow import FlowResultType

    fake = FakeTransport(ANSWERS)
    entry = await setup_cul(hass, fake)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["menu_options"] == ["pair", "settings"]
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "pair"})
    assert result["step_id"] == "pair"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"code1": 28, "code2": 80})
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    assert result["description_placeholders"]["code"] == "028 080"
    await settle(hass)
    assert written(fake) == [REPORT]
    fake.feed("T1C506669FFFC")
    await settle(hass)
    result = await hass.config_entries.options.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "paired"
    assert entry.options == {}  # pairing does not touch the options (no reload)
    await hass.config_entries.async_unload(entry.entry_id)


async def test_pair_options_flow_timeout(hass):

    entry = await setup_cul(hass, FakeTransport(ANSWERS))
    hub = entry.runtime_data
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "pair"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"code1": 28, "code2": 80})
    with patch("custom_components.cul.hub._time.time", return_value=hub._pairing["1c50"]):
        hub._async_pair_tick()
    await settle(hass)
    result = await hass.config_entries.options.async_configure(result["flow_id"])
    assert result["reason"] == "pair_failed"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_restart_button(hass):
    fake = FakeTransport(ANSWERS)
    entry = await setup_cul(hass, fake)
    await hass.services.async_call("button", "press", {"entity_id": "button.cul_1034_restart"}, blocking=True)
    assert "B00" in fake.written
    await hass.config_entries.async_unload(entry.entry_id)
