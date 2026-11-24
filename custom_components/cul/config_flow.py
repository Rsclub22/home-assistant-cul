"""Config flow for CUL."""

from __future__ import annotations

import asyncio
import os
import random
import re
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
)
from homeassistant.helpers.service_info.usb import UsbServiceInfo

from . import hub
from .const import (
    CONF_BAUDRATE,
    CONF_CONNECTION,
    CONF_DEVICE,
    CONF_FHTID,
    CONF_MIGRATE,
    CONN_SERIAL,
    CONN_TCP,
    DEFAULT_BAUDRATE,
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
    DOMAIN,
    OPT_TIME_SYNC,
    OPT_TIMEOUT,
)
from .culpy.cul import probe
from .hub import fht_code_display, fht_code_from_parts

FHTID_RE = re.compile(r"^[0-9A-Fa-f]{4}$")
BY_ID = "/dev/serial/by-id"


def random_fhtid() -> str:
    """Both bytes 1..99: the FHT80b shows codes as two decimal numbers."""
    return f"{random.randint(1, 99):02X}{random.randint(1, 99):02X}"


def serial_by_id(device: str) -> str:
    """Stable /dev/serial/by-id path for a device node, if there is one."""
    if not os.path.isdir(BY_ID):
        return device
    for entry in os.scandir(BY_ID):
        if entry.is_symlink() and os.path.realpath(entry.path) == os.path.realpath(device):
            return entry.path
    return device


def list_serial_ports() -> list[SelectOptionDict]:
    """USB serial ports only (no /dev/ttyS*), CULs first, with a readable label."""
    from serialx import list_serial_ports as _list

    options: dict[str, tuple[bool, str]] = {}
    for port in _list():
        if port.vid is None:
            continue
        path = serial_by_id(port.device)
        name = " - ".join(x for x in (port.product, port.manufacturer) if x) or "USB serial"
        is_cul = (port.vid, port.pid) == (0x03EB, 0x204B) or "cul" in name.lower()
        options[path] = (is_cul, f"{name} ({path})")
    ordered = sorted(options.items(), key=lambda kv: (not kv[1][0], kv[1][1]))
    return [SelectOptionDict(value=path, label=label) for path, (_, label) in ordered]


class CulConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._usb_name = ""

    def _migrate_default(self) -> bool:
        return bool(self.hass.config_entries.async_entries("fht_heating"))

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=["serial", "network"])

    async def async_step_network(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            # before the probe: with ser2net max-connections 1 a running entry blocks it
            self._async_abort_entries_match(
                {CONF_HOST: user_input[CONF_HOST], CONF_PORT: user_input[CONF_PORT]})
            data = {CONF_CONNECTION: CONN_TCP, **user_input}
            if (result := await self._async_probe(data, errors)) is not None:
                return result
        schema = vol.Schema({
            vol.Required(CONF_HOST): str,
            vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
            vol.Required(CONF_MIGRATE, default=self._migrate_default()): bool,
        })
        return self.async_show_form(
            step_id="network", data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors)

    async def async_step_serial(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._async_abort_entries_match({CONF_DEVICE: user_input[CONF_DEVICE]})
            data = {CONF_CONNECTION: CONN_SERIAL, **user_input}
            if (result := await self._async_probe(data, errors)) is not None:
                return result
        ports = await self.hass.async_add_executor_job(list_serial_ports)
        schema = vol.Schema({
            vol.Required(CONF_DEVICE): SelectSelector(
                SelectSelectorConfig(options=ports, custom_value=True)),
            vol.Required(CONF_BAUDRATE, default=DEFAULT_BAUDRATE): int,
            vol.Required(CONF_MIGRATE, default=self._migrate_default()): bool,
        })
        return self.async_show_form(
            step_id="serial", data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors)

    async def async_step_usb(self, discovery_info: UsbServiceInfo) -> ConfigFlowResult:
        device = await self.hass.async_add_executor_job(serial_by_id, discovery_info.device)
        # a placeholder until the probe reads the FHT-ID; lets the user ignore this stick
        await self.async_set_unique_id(f"usb_{discovery_info.serial_number or device}")
        self._abort_if_unique_id_configured()
        self._async_abort_entries_match({CONF_DEVICE: device})
        self._data = {CONF_CONNECTION: CONN_SERIAL, CONF_DEVICE: device,
                      CONF_BAUDRATE: DEFAULT_BAUDRATE}
        self._usb_name = discovery_info.description or "CUL"
        self.context["title_placeholders"] = {"name": self._usb_name}
        return await self.async_step_usb_confirm()

    async def async_step_usb_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if (result := await self._async_probe({**self._data, **user_input}, errors)) is not None:
                return result
        schema = vol.Schema({vol.Required(CONF_MIGRATE, default=self._migrate_default()): bool})
        return self.async_show_form(
            step_id="usb_confirm", data_schema=schema, errors=errors,
            description_placeholders={"name": self._usb_name, "device": self._data[CONF_DEVICE]})

    async def _async_probe(
        self, data: dict[str, Any], errors: dict[str, str]
    ) -> ConfigFlowResult | None:
        """Read the FHT-ID from the CUL. None: show the form again with errors."""
        try:
            _, current = await probe(hub.create_transport(data))
        except (OSError, ConnectionError, TimeoutError):
            errors["base"] = "cannot_connect"
            return None
        self._data = data
        if current is None:
            return await self.async_step_fhtid()
        return await self._async_finish(current.upper())

    async def async_step_fhtid(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """The CUL has no FHT-ID yet (0000): propose one; the hub writes it with T01."""
        errors: dict[str, str] = {}
        if user_input is not None:
            fhtid = user_input[CONF_FHTID].strip().upper()
            if not FHTID_RE.match(fhtid) or fhtid == "0000":
                errors[CONF_FHTID] = "invalid_fhtid"
            else:
                return await self._async_finish(fhtid)
        schema = vol.Schema({vol.Required(CONF_FHTID, default=random_fhtid()): str})
        return self.async_show_form(step_id="fhtid", data_schema=schema, errors=errors)

    async def _async_finish(self, fhtid: str) -> ConfigFlowResult:
        await self.async_set_unique_id(fhtid, raise_on_progress=False)
        # same CUL found again on a new path (e.g. moved from ser2net to USB): follow it
        connection = {k: v for k, v in self._data.items() if k != CONF_MIGRATE}
        self._abort_if_unique_id_configured(updates=connection)
        return self.async_create_entry(
            title=f"CUL {fhtid}", data={**self._data, CONF_FHTID: fhtid})

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> CulOptionsFlow:
        return CulOptionsFlow()


class CulOptionsFlow(OptionsFlow):
    def __init__(self) -> None:
        self._address = ""
        self._task: asyncio.Task[bool] | None = None

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=["pair", "settings"])

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        opts = self.config_entry.options
        schema = vol.Schema({
            vol.Required(OPT_TIMEOUT, default=opts.get(OPT_TIMEOUT, DEFAULT_TIMEOUT)):
                vol.All(int, vol.Range(min=300)),
            vol.Required(OPT_TIME_SYNC, default=opts.get(OPT_TIME_SYNC, True)): bool,
        })
        return self.async_show_form(step_id="settings", data_schema=schema)

    async def async_step_pair(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Code 1 and 2 as the FHT80b shows them under "CodE", e.g. 028 and 080."""
        if self.config_entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")
        if user_input is not None:
            self._address = fht_code_from_parts(int(user_input["code1"]), int(user_input["code2"]))
            self.config_entry.runtime_data.async_pair(self._address)
            return await self.async_step_pair_wait()
        code = vol.All(NumberSelector(NumberSelectorConfig(
            min=0, max=99, step=1, mode=NumberSelectorMode.BOX)), vol.Coerce(int))
        schema = vol.Schema({vol.Required("code1"): code, vol.Required("code2"): code})
        return self.async_show_form(step_id="pair", data_schema=schema)

    async def async_step_pair_wait(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        hub_ = self.config_entry.runtime_data
        if self._task is None:
            # background: waits up to 15 min and must not hold up async_block_till_done
            self._task = self.hass.async_create_background_task(
                hub_.async_wait_paired(self._address), f"cul pair {self._address}")
        placeholders = {"address": self._address, "code": fht_code_display(self._address)}
        if not self._task.done():
            return self.async_show_progress(
                step_id="pair_wait", progress_action="pairing", progress_task=self._task,
                description_placeholders=placeholders)
        paired = self._task.result()
        return self.async_show_progress_done(next_step_id="paired" if paired else "pair_failed")

    async def async_step_paired(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_abort(
            reason="paired", description_placeholders={"code": fht_code_display(self._address)})

    async def async_step_pair_failed(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_abort(
            reason="pair_failed", description_placeholders={"code": fht_code_display(self._address)})
