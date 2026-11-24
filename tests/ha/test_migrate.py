"""Migration from fht_heating."""

from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryDisabler
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_registry import RegistryEntryDisabler, RegistryEntryHider
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cul.culpy.transport.fake import FakeTransport
from custom_components.cul.migrate import map_old_unique_id

from .helpers import ANSWERS, setup_cul

OLD = "http://192.0.2.10:8086"


def test_map_old_unique_id():
    assert map_old_unique_id(f"{OLD}_FHT_1c50") == ("1c50", "climate")
    assert map_old_unique_id(f"{OLD}_FHT_1c50_window") == ("1c50", "window")
    assert map_old_unique_id(f"{OLD}_FHT_1C50_mon-from1") == ("1c50", "mon-from1")
    assert map_old_unique_id("something_else") is None


def _add_old(hass):
    old_entry = MockConfigEntry(domain="fht_heating", title="FHT")
    old_entry.add_to_hass(hass)
    reg = er.async_get(hass)
    rows = [
        ("climate", f"{OLD}_FHT_1c50", "fht_1c50_2"),
        ("binary_sensor", f"{OLD}_FHT_1c50_window", "fht_1c50_window_sensor_2"),
        ("number", f"{OLD}_FHT_1c50_day-temp", "fht_1c50_day_temp"),
        ("select", f"{OLD}_FHT_1c50_mode", "fht_1c50_mode"),
        ("time", f"{OLD}_FHT_1c50_mon-from1", "fht_1c50_mon_from1"),
        ("sensor", f"{OLD}_FHT_1c50_unknownthing", "fht_1c50_unknownthing"),
    ]
    for domain, uid, obj in rows:
        reg.async_get_or_create(domain, "fht_heating", uid, suggested_object_id=obj,
                                config_entry=old_entry)
    return old_entry, reg, rows


async def test_migration_keeps_entity_ids(hass):
    old_entry, reg, rows = _add_old(hass)

    entry = await setup_cul(hass, FakeTransport(ANSWERS), data={"migrate": True})

    for domain, _uid, obj in rows[:5]:
        e = reg.async_get(f"{domain}.{obj}")
        assert e.platform == "cul", obj
        assert e.unique_id.startswith("1034_fht_1c50_")
        assert e.config_entry_id == entry.entry_id
        # the migrated registry entry is the one the platform uses (has state)
        assert hass.states.get(e.entity_id) is not None, obj
    assert reg.async_get("climate.fht_1c50_2").unique_id == "1034_fht_1c50_climate"
    assert reg.async_get("binary_sensor.fht_1c50_window_sensor_2").unique_id == "1034_fht_1c50_window"
    assert reg.async_get("number.fht_1c50_day_temp").unique_id == "1034_fht_1c50_day-temp"
    assert reg.async_get("select.fht_1c50_mode").unique_id == "1034_fht_1c50_mode"
    assert reg.async_get("time.fht_1c50_mon_from1").unique_id == "1034_fht_1c50_mon-from1"
    assert reg.async_get("sensor.fht_1c50_unknownthing").platform == "fht_heating"
    assert old_entry.disabled_by is ConfigEntryDisabler.USER
    assert entry.data["migrated"] is True
    assert hass.states.get("climate.fht_1c50_2") is not None
    # no duplicate cul entities with a different entity_id for the migrated unique_ids
    cul_uids = [e.unique_id for e in reg.entities.values() if e.platform == "cul"]
    assert len(cul_uids) == len(set(cul_uids))
    assert hass.states.get("climate.fht_1c50") is None
    await hass.config_entries.async_unload(entry.entry_id)


async def test_reload_after_migration_is_noop(hass):
    old_entry, reg, rows = _add_old(hass)
    entry = await setup_cul(hass, FakeTransport(ANSWERS), data={"migrate": True})
    before = {e.entity_id: (e.unique_id, e.platform) for e in reg.entities.values()}
    assert await hass.config_entries.async_unload(entry.entry_id)
    # a new old-style entity appears (old entry stays disabled): a reload must not touch it
    reg.async_get_or_create("sensor", "fht_heating", f"{OLD}_FHT_1c50_x", config_entry=old_entry)
    with patch("custom_components.cul.async_migrate_fht_heating") as mig, patch(
        "custom_components.cul.hub.create_transport", return_value=FakeTransport(ANSWERS)
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        mig.assert_not_called()
    after = {e.entity_id: (e.unique_id, e.platform) for e in reg.entities.values()}
    for k, v in before.items():
        assert after[k] == v
    await hass.config_entries.async_unload(entry.entry_id)


async def test_migration_keeps_customizations(hass):
    old_entry, reg, rows = _add_old(hass)
    area = ar.async_get(hass).async_create("Wohnzimmer")
    climate = reg.async_get("climate.fht_1c50_2")
    number = reg.async_get("number.fht_1c50_day_temp")
    select = reg.async_get("select.fht_1c50_mode")
    time_e = reg.async_get("time.fht_1c50_mon_from1")
    reg.async_update_entity(climate.entity_id, name="Wohnzimmer Heizung", icon="mdi:radiator",
                            area_id=area.id, aliases={"Heizung"}, labels={"lbl"})
    reg.async_update_entity_options(number.entity_id, "number", {"unit_of_measurement": "K"})
    reg.async_update_entity(select.entity_id, hidden_by=RegistryEntryHider.USER)
    reg.async_update_entity(time_e.entity_id, disabled_by=RegistryEntryDisabler.USER)
    ids = {e.entity_id: e.id for e in (climate, number, select, time_e)}
    created = climate.created_at

    entry = await setup_cul(hass, FakeTransport(ANSWERS), data={"migrate": True})

    c = reg.async_get("climate.fht_1c50_2")
    assert c.platform == "cul" and c.id == ids[c.entity_id] and c.created_at == created
    assert c.name == "Wohnzimmer Heizung" and c.icon == "mdi:radiator"
    assert c.area_id == area.id and c.aliases == {"Heizung"} and c.labels == {"lbl"}
    assert c.disabled_by is None
    assert hass.states.get(c.entity_id) is not None
    n = reg.async_get("number.fht_1c50_day_temp")
    assert n.options["number"] == {"unit_of_measurement": "K"}
    assert n.disabled_by is None and n.id == ids[n.entity_id]
    sel = reg.async_get("select.fht_1c50_mode")
    assert sel.hidden_by is RegistryEntryHider.USER and sel.disabled_by is None
    t = reg.async_get("time.fht_1c50_mon_from1")
    assert t.disabled_by is RegistryEntryDisabler.USER
    assert hass.states.get(t.entity_id) is None
    await hass.config_entries.async_unload(entry.entry_id)


async def test_migration_ignores_stale_deleted_entity(hass):
    # an earlier cul setup created climate.fht_1c50 and was deleted again
    throwaway = MockConfigEntry(domain="cul", unique_id="1034", title="old cul")
    throwaway.add_to_hass(hass)
    reg = er.async_get(hass)
    stale = reg.async_get_or_create("climate", "cul", "1034_fht_1c50_climate",
                                    suggested_object_id="fht_1c50", config_entry=throwaway)
    assert stale.entity_id == "climate.fht_1c50"
    reg.async_remove(stale.entity_id)
    assert ("climate", "cul", "1034_fht_1c50_climate") in reg.deleted_entities
    _add_old(hass)

    entry = await setup_cul(hass, FakeTransport(ANSWERS), data={"migrate": True})

    assert reg.async_get("climate.fht_1c50_2").unique_id == "1034_fht_1c50_climate"
    assert reg.async_get("climate.fht_1c50") is None
    assert hass.states.get("climate.fht_1c50_2") is not None
    await hass.config_entries.async_unload(entry.entry_id)


async def test_silent_device_survives_empty_store(hass, hass_storage):
    old_entry = MockConfigEntry(domain="fht_heating", title="FHT")
    old_entry.add_to_hass(hass)
    reg = er.async_get(hass)
    reg.async_get_or_create("climate", "fht_heating", f"{OLD}_FHT_0e52",
                            suggested_object_id="fht_0e52", config_entry=old_entry)
    entry = await setup_cul(hass, FakeTransport(ANSWERS), data={"migrate": True})
    assert hass.states.get("climate.fht_0e52") is not None
    assert await hass.config_entries.async_unload(entry.entry_id)
    # hub store lost: device list empty, only registry knows the code
    hass_storage.clear()
    with patch("custom_components.cul.hub.create_transport", return_value=FakeTransport(ANSWERS)):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.data["migrated"] is True
    state = hass.states.get("climate.fht_0e52")
    assert state is not None and not state.attributes.get("restored")  # live entity, not a leftover
    assert "fht:0e52" in entry.runtime_data.devices
    e = reg.async_get("climate.fht_0e52")
    assert e.device_id is not None
    assert dr.async_get(hass).async_get(e.device_id) is not None
    await hass.config_entries.async_unload(entry.entry_id)


async def test_migration_keeps_device_area_and_name(hass):
    old_entry, reg, rows = _add_old(hass)
    areas = ar.async_get(hass)
    living, bath = areas.async_create("Wohnzimmer"), areas.async_create("Bad")
    dev_reg = dr.async_get(hass)
    old_dev = dev_reg.async_get_or_create(
        config_entry_id=old_entry.entry_id, identifiers={("fht_heating", "1c50")}, name="FHT 1c50")
    dev_reg.async_update_device(old_dev.id, area_id=living.id, name_by_user="Heizung Wohnzimmer")
    for domain, _uid, obj in rows:
        reg.async_update_entity(f"{domain}.{obj}", device_id=old_dev.id)
    reg.async_update_entity("number.fht_1c50_day_temp", name="Tagtemperatur Bad", area_id=bath.id)

    entry = await setup_cul(hass, FakeTransport(ANSWERS), data={"migrate": True})

    new_dev = dev_reg.async_get_device_by_identifier(("cul", "fht:1c50"), entry.entry_id)
    assert new_dev is not None
    assert new_dev.area_id == living.id
    assert new_dev.name_by_user == "Heizung Wohnzimmer"
    assert reg.async_get("climate.fht_1c50_2").device_id == new_dev.id
    assert reg.async_get("number.fht_1c50_day_temp").area_id == bath.id
    await hass.config_entries.async_unload(entry.entry_id)


async def test_migration_skips_duplicate_new_uid(hass, caplog):
    old_entry, reg, rows = _add_old(hass)
    # second fht_heating instance (other URL) with the same FHT code and key
    reg.async_get_or_create("binary_sensor", "fht_heating", "http://other:8086_FHT_1C50_window",
                            suggested_object_id="fht_1c50_window_other", config_entry=old_entry)
    # a cul entity with the target unique_id already exists (other cul entry, still present)
    other = MockConfigEntry(domain="cul", unique_id="9999", title="other cul")
    other.add_to_hass(hass)
    reg.async_get_or_create("select", "cul", "1034_fht_1c50_mode",
                            suggested_object_id="already_there", config_entry=other)

    entry = await setup_cul(hass, FakeTransport(ANSWERS), data={"migrate": True})

    assert entry.data["migrated"] is True
    assert reg.async_get("binary_sensor.fht_1c50_window_sensor_2").platform == "cul"
    assert reg.async_get("binary_sensor.fht_1c50_window_other").platform == "fht_heating"
    assert reg.async_get("select.fht_1c50_mode").platform == "fht_heating"
    assert reg.async_get("climate.fht_1c50_2").platform == "cul"  # rest moved
    assert "binary_sensor.fht_1c50_window_other" in caplog.text
    await hass.config_entries.async_unload(entry.entry_id)
