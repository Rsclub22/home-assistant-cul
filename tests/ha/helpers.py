"""Helpers for HA tests."""

import asyncio
from unittest.mock import patch

from homeassistant.const import CONF_HOST, CONF_PORT
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cul.const import CONF_FHTID, CONF_MIGRATE, DOMAIN

ANSWERS = {"V": "V 1.67 CUL868", "T01": "1034", "T03": "FF", "X": "21  900"}


def rf(payload: str) -> str:
    return f"T{payload}4A"


async def settle(hass) -> None:
    for _ in range(20):
        await asyncio.sleep(0.01)
    await hass.async_block_till_done()


async def setup_cul(hass, fake, *, options=None, data=None, unique_id="1034") -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=unique_id,
        title=f"CUL {unique_id}",
        data={CONF_HOST: "cul-host", CONF_PORT: 2323, CONF_FHTID: "1034",
              CONF_MIGRATE: False, **(data or {})},
        options=options or {},
    )
    entry.add_to_hass(hass)
    with patch("custom_components.cul.hub.create_transport", return_value=fake):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await settle(hass)
    return entry


def written(fake, prefix="T") -> list[str]:
    return [w for w in fake.written if w.startswith(prefix) and w not in ("T01", "T03")]
