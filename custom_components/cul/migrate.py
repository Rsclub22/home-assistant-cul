"""Take over entities from the fht_heating integration (FHEM WEBapi)."""

from __future__ import annotations

import logging
import re

from homeassistant.config_entries import ConfigEntry, ConfigEntryDisabler
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_registry import RegistryEntryDisabler

from .const import DOMAIN
from .culpy.protocols.fht import SCHEDULE_KEYS

_LOGGER = logging.getLogger(__name__)
OLD_DOMAIN = "fht_heating"
OLD_RE = re.compile(r"_FHT_([0-9a-fA-F]{4})(?:_(.+))?$")
KEY_PLATFORM = {
    "climate": "climate",
    "window": "binary_sensor",
    "mode": "select",
    "day-temp": "number",
    "night-temp": "number",
    "windowopen-temp": "number",
    "manu-temp": "number",
    "lowtemp-offset": "number",
    **{k: "time" for k in SCHEDULE_KEYS},
}


def map_old_unique_id(unique_id: str) -> tuple[str, str] | None:
    m = OLD_RE.search(unique_id)
    if not m:
        return None
    return m.group(1).lower(), m.group(2) or "climate"


async def async_migrate_fht_heating(
    hass: HomeAssistant, entry: ConfigEntry
) -> tuple[list[str], set[str]]:
    for old in hass.config_entries.async_entries(OLD_DOMAIN):
        if old.disabled_by is None:
            await hass.config_entries.async_set_disabled_by(old.entry_id, ConfigEntryDisabler.USER)
    reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    moved: list[str] = []
    codes: set[str] = set()
    # area/name the user gave the old device; entities without own area inherit it
    old_devices: dict[str, tuple[str | None, str | None]] = {}
    for old_entity in list(reg.entities.values()):
        if old_entity.platform != OLD_DOMAIN:
            continue
        mapped = map_old_unique_id(old_entity.unique_id)
        domain, object_id = old_entity.entity_id.split(".", 1)
        if mapped is None or KEY_PLATFORM.get(mapped[1]) != domain:
            _LOGGER.warning("fht_heating entity %s not taken over", old_entity.entity_id)
            continue
        code, key = mapped
        new_uid = f"{entry.unique_id}_fht_{code}_{key}"
        # checked before touching this entity: HA only rejects unique_id clashes on the old
        # platform, so a second fht_heating entity with the same code/key (or an existing cul
        # entity) would silently become a duplicate cul registry entry
        if (taken := reg.async_get_entity_id(domain, DOMAIN, new_uid)) is not None:
            _LOGGER.warning(
                "fht_heating entity %s not taken over: %s already has unique_id %s",
                old_entity.entity_id, taken, new_uid)
            continue
        if code not in old_devices and old_entity.device_id:
            old_dev = dev_reg.async_get(old_entity.device_id)
            if old_dev and (old_dev.area_id or old_dev.name_by_user):
                old_devices[code] = (old_dev.area_id, old_dev.name_by_user)
        # a stale entry from an earlier, deleted cul setup would hijack the entity_id
        if reg.deleted_entities.pop((domain, DOMAIN, new_uid), None) is not None:
            reg.async_schedule_save()
        # update in place: keeps name, icon, area, labels, options, hidden/disabled, id
        moved_entity = reg.async_update_entity_platform(
            old_entity.entity_id, DOMAIN,
            new_config_entry_id=entry.entry_id, new_unique_id=new_uid, new_device_id=None,
        )
        if moved_entity.entity_id != old_entity.entity_id:
            _LOGGER.error(
                "fht_heating entity %s became %s during takeover",
                old_entity.entity_id, moved_entity.entity_id,
            )
        if moved_entity.disabled_by is RegistryEntryDisabler.CONFIG_ENTRY:
            # only set because the old config entry was disabled
            reg.async_update_entity(moved_entity.entity_id, disabled_by=None)
        moved.append(old_entity.entity_id)
        codes.add(code)
    _async_take_over_devices(hass, entry, old_devices)
    _LOGGER.info("Took over %d fht_heating entities for %s", len(moved), sorted(codes))
    return moved, codes


@callback
def _async_take_over_devices(
    hass: HomeAssistant, entry: ConfigEntry, old_devices: dict[str, tuple[str | None, str | None]]
) -> None:
    """Create the cul FHT devices now (as the entities would) and copy area and user name."""
    dev_reg = dr.async_get(hass)
    cul_device = dev_reg.async_get_device_by_identifier((DOMAIN, f"cul:{entry.unique_id}"), entry.entry_id)
    for code, (area_id, name_by_user) in old_devices.items():
        device = dev_reg.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, f"fht:{code}")},
            name=f"FHT {code}",
            manufacturer="ELV",
            model="FHT80b",
            via_device_id=cul_device.id if cul_device else None,
        )
        dev_reg.async_update_device(
            device.id,
            area_id=device.area_id or area_id,
            name_by_user=device.name_by_user or name_by_user,
        )


@callback
def fht_codes_from_registry(hass: HomeAssistant, entry: ConfigEntry) -> set[str]:
    """FHT addresses this entry already owns in the entity registry."""
    prefix = f"{entry.unique_id}_fht_"
    reg = er.async_get(hass)
    codes: set[str] = set()
    for e in er.async_entries_for_config_entry(reg, entry.entry_id):
        if e.platform == DOMAIN and e.unique_id.startswith(prefix):
            code = e.unique_id[len(prefix):].split("_", 1)[0]
            if re.fullmatch(r"[0-9a-f]{4}", code):
                codes.add(code)
    return codes
