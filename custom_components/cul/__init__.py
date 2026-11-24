"""CUL (culfw) integration."""

from __future__ import annotations

import re

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.helpers.typing import ConfigType

from .const import CONF_MIGRATE, DATA_MIGRATED, DOMAIN
from .hub import CulHub, fht_code_from_parts
from .migrate import async_migrate_fht_heating, fht_codes_from_registry

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR, Platform.BUTTON, Platform.CLIMATE, Platform.NUMBER, Platform.SELECT, Platform.SENSOR, Platform.TIME,
]

type CulConfigEntry = ConfigEntry[CulHub]

def fht_code(value: object) -> str:
    """FHT80b code as shown on the device ("028 080": code 1 and 2, decimal) or hex ("1c50")."""
    text = cv.string(value).strip()
    if m := re.fullmatch(r"(\d{1,3})\s+(\d{1,3})", text):
        code1, code2 = int(m.group(1)), int(m.group(2))
        if code1 <= 99 and code2 <= 99:
            return fht_code_from_parts(code1, code2)
    elif re.fullmatch(r"[0-9A-Fa-f]{4}", text):
        return text.lower()
    raise vol.Invalid('use the code shown on the FHT80b, e.g. "028 080", or 4 hex digits')


def _loaded_entries(hass: HomeAssistant, entry_id: str | None) -> list[ConfigEntry]:
    if entry_id is not None:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
            raise ServiceValidationError(f"CUL config entry {entry_id} not found or not loaded")
        return [entry]
    entries = list(hass.config_entries.async_loaded_entries(DOMAIN))
    if not entries:
        raise HomeAssistantError("No CUL is connected")
    return entries


def _raw_line(value: object) -> str:
    line = cv.string(value).strip()
    if not line:
        raise vol.Invalid("line must not be empty")
    if not all(" " <= c <= "~" for c in line):
        raise vol.Invalid("line must be printable ASCII on a single line")
    return line


CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async def send_raw(call: ServiceCall) -> None:
        entries = _loaded_entries(hass, call.data.get("config_entry_id"))
        if call.data["line"].upper().startswith("T01") and not call.data["confirm"]:
            # T01xxxx changes the FHT ID: every FHT80b would have to be paired again
            raise ServiceValidationError("T01 changes the CUL FHT ID; pass confirm: true to send it")
        for entry in entries:
            try:
                await entry.runtime_data.send_raw(call.data["line"])
            except (ConnectionError, OSError, TimeoutError) as err:
                raise HomeAssistantError(f"CUL not reachable: {err}") from err

    # admin only: raw lines can make the CUL deaf (X00) or re-pair all FHTs (T01)
    async_register_admin_service(hass, DOMAIN, "send_raw", send_raw, vol.Schema({
        vol.Required("line"): _raw_line,
        vol.Optional("config_entry_id"): cv.string,
        vol.Optional("confirm", default=False): cv.boolean,
    }))

    async def fht_pair(call: ServiceCall) -> None:
        entries = _loaded_entries(hass, call.data.get("config_entry_id"))
        if len(entries) > 1:
            raise ServiceValidationError("Several CULs are set up: choose one")
        entries[0].runtime_data.async_pair(call.data["code"])

    hass.services.async_register(DOMAIN, "fht_pair", fht_pair, vol.Schema({
        vol.Required("code"): fht_code,
        vol.Optional("config_entry_id"): cv.string,
    }))
    return True


async def async_setup_entry(hass: HomeAssistant, entry: CulConfigEntry) -> bool:
    hub = CulHub(hass, entry)
    await hub.async_load()
    hub.async_register_cul_device()  # before migration: taken-over FHT devices hang below it
    if entry.data.get(CONF_MIGRATE) and not entry.data.get(DATA_MIGRATED):
        await async_migrate_fht_heating(hass, entry)
        hass.config_entries.async_update_entry(entry, data={**entry.data, DATA_MIGRATED: True})
    for code in fht_codes_from_registry(hass, entry):
        hub.ensure_device("fht", code)
    entry.runtime_data = hub
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await hub.async_start()
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: CulConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: CulConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_stop()
    return unloaded


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: CulConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Let the user delete FHT/FHT80TF devices (e.g. strays); the CUL itself stays."""
    keys = [ident for domain, ident in device_entry.identifiers if domain == DOMAIN]
    if any(k.startswith("cul:") for k in keys) or entry.state is not ConfigEntryState.LOADED:
        return False  # unloaded: the hub store would bring the device back on next start
    hub: CulHub = entry.runtime_data
    for key in keys:
        hub.async_remove_device(key)
    return True
