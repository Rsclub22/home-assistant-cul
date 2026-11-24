"""Config and options flow tests."""

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.usb import UsbServiceInfo

from custom_components.cul.config_flow import random_fhtid
from custom_components.cul.const import (
    CONF_BAUDRATE,
    CONF_CONNECTION,
    CONF_DEVICE,
    CONF_FHTID,
    CONF_MIGRATE,
    DOMAIN,
    OPT_TIME_SYNC,
    OPT_TIMEOUT,
)
from custom_components.cul.culpy.transport.fake import FakeTransport
from custom_components.cul.culpy.transport.serial import SerialTransport
from custom_components.cul.culpy.transport.tcp import TcpTransport
from custom_components.cul.hub import create_transport

from .helpers import ANSWERS, settle, setup_cul

NET_INPUT = {CONF_HOST: "cul-host", CONF_PORT: 2323, CONF_MIGRATE: False}
DEV = "/dev/serial/by-id/usb-busware.de_CUL868-if00"
SERIAL_INPUT = {CONF_DEVICE: DEV, CONF_BAUDRATE: 9600, CONF_MIGRATE: False}
USB_INFO = UsbServiceInfo(
    device="/dev/ttyACM0", vid="03EB", pid="204B", serial_number=None,
    manufacturer="busware.de", description="CUL868")
PROBE = "custom_components.cul.config_flow.probe"
SETUP = "custom_components.cul.async_setup_entry"


async def start(hass, step):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["serial", "network"]
    ports = [{"value": DEV, "label": f"CUL868 - busware.de ({DEV})"}]
    with patch("custom_components.cul.config_flow.list_serial_ports", return_value=ports):
        return await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": step})


async def test_network_flow_reads_fhtid(hass):
    result = await start(hass, "network")
    assert result["step_id"] == "network"
    with patch(PROBE, AsyncMock(return_value=("V 1.67", "1034"))), patch(SETUP, AsyncMock(return_value=True)):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], NET_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "CUL 1034"
    assert result["data"] == {**NET_INPUT, CONF_CONNECTION: "tcp", CONF_FHTID: "1034"}
    assert result["result"].unique_id == "1034"


async def test_serial_flow(hass):
    result = await start(hass, "serial")
    assert result["step_id"] == "serial"
    with patch(PROBE, AsyncMock(return_value=("V 1.67", "0e52"))), patch(SETUP, AsyncMock(return_value=True)):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], SERIAL_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {**SERIAL_INPUT, CONF_CONNECTION: "serial", CONF_FHTID: "0E52"}


async def test_fhtid_0000_proposes_random(hass):
    result = await start(hass, "serial")
    with patch(PROBE, AsyncMock(return_value=("V 1.67", None))):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], SERIAL_INPUT)
    assert result["step_id"] == "fhtid"
    proposed = result["data_schema"]({})[CONF_FHTID]
    assert len(proposed) == 4 and 1 <= int(proposed[:2], 16) <= 99 and 1 <= int(proposed[2:], 16) <= 99
    for bad in ("0000", "12G4"):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_FHTID: bad})
        assert result["errors"] == {CONF_FHTID: "invalid_fhtid"}
    with patch(SETUP, AsyncMock(return_value=True)):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_FHTID: "2a3b"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_FHTID] == "2A3B"


def test_random_fhtid_shows_as_decimal_pairs():
    for _ in range(200):
        code = random_fhtid()
        assert 1 <= int(code[:2], 16) <= 99 and 1 <= int(code[2:], 16) <= 99


async def test_cannot_connect(hass):
    result = await start(hass, "network")
    with patch(PROBE, AsyncMock(side_effect=OSError)):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], NET_INPUT)
    assert result["errors"] == {"base": "cannot_connect"}


async def test_usb_discovery(hass):
    with patch("custom_components.cul.config_flow.serial_by_id", return_value=DEV):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USB}, data=USB_INFO)
    assert result["step_id"] == "usb_confirm"
    assert result["description_placeholders"] == {"name": "CUL868", "device": DEV}
    with patch(PROBE, AsyncMock(return_value=("V 1.67", "1034"))), patch(SETUP, AsyncMock(return_value=True)):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_MIGRATE: False})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {**SERIAL_INPUT, CONF_CONNECTION: "serial", CONF_FHTID: "1034"}
    assert result["result"].unique_id == "1034"


async def test_usb_discovery_known_device_aborts(hass):
    entry = await setup_cul(hass, FakeTransport(ANSWERS), data={CONF_CONNECTION: "serial", CONF_DEVICE: DEV})
    with patch("custom_components.cul.config_flow.serial_by_id", return_value=DEV):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USB}, data=USB_INFO)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_same_cul_on_new_path_updates_entry(hass):
    """Moved from ser2net to USB: the FHT-ID identifies it, the entry follows."""
    entry = await setup_cul(hass, FakeTransport(ANSWERS))
    await hass.config_entries.async_unload(entry.entry_id)
    result = await start(hass, "serial")
    with patch(PROBE, AsyncMock(return_value=("V 1.67", "1034"))), \
         patch("custom_components.cul.hub.create_transport", return_value=FakeTransport(ANSWERS)):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], SERIAL_INPUT)
        await settle(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_CONNECTION] == "serial" and entry.data[CONF_DEVICE] == DEV
    assert entry.data[CONF_MIGRATE] is False  # not overwritten by the new flow
    await hass.config_entries.async_unload(entry.entry_id)


async def test_options_flow(hass):
    entry = await setup_cul(hass, FakeTransport(ANSWERS))
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "settings"})
    with patch("custom_components.cul.hub.create_transport", return_value=FakeTransport(ANSWERS)):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {OPT_TIMEOUT: 3600, OPT_TIME_SYNC: False})
        await settle(hass)  # update listener reloads the entry in a background task
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {OPT_TIMEOUT: 3600, OPT_TIME_SYNC: False}
    await hass.config_entries.async_unload(entry.entry_id)


async def test_duplicate_aborts_before_probe(hass):
    entry = await setup_cul(hass, FakeTransport(ANSWERS))
    result = await start(hass, "network")
    probe = AsyncMock(side_effect=OSError)  # ser2net max-connections 1: probe would fail
    with patch(PROBE, probe):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], NET_INPUT)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    probe.assert_not_called()
    await hass.config_entries.async_unload(entry.entry_id)


def test_create_transport():
    old = create_transport({CONF_HOST: "h", CONF_PORT: 1})  # entry from 0.1.0b1
    assert isinstance(old, TcpTransport) and (old.host, old.port) == ("h", 1)
    ser = create_transport({CONF_CONNECTION: "serial", CONF_DEVICE: DEV, CONF_BAUDRATE: 38400})
    assert isinstance(ser, SerialTransport) and (ser.device, ser.baudrate) == (DEV, 38400)


def test_list_serial_ports_usb_only_cul_first():
    from types import SimpleNamespace as P

    from custom_components.cul.config_flow import list_serial_ports

    ports = [
        P(device="/dev/ttyS0", vid=None, pid=None, product=None, manufacturer=None),
        P(device="/dev/ttyUSB0", vid=0x10C4, pid=0xEA60, product="CP2102", manufacturer="Silabs"),
        P(device="/dev/ttyACM0", vid=0x03EB, pid=0x204B, product="CUL868", manufacturer="busware.de"),
    ]
    with patch("serialx.list_serial_ports", return_value=ports), \
         patch("custom_components.cul.config_flow.serial_by_id", side_effect=lambda d: d):
        options = list_serial_ports()
    assert [o["value"] for o in options] == ["/dev/ttyACM0", "/dev/ttyUSB0"]
    assert options[0]["label"] == "CUL868 - busware.de (/dev/ttyACM0)"
