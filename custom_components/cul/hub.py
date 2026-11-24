"""CulHub: glue between culpy and Home Assistant."""

from __future__ import annotations

import asyncio
import logging
import time as _time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import time, timedelta
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_change, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BAUDRATE,
    CONF_CONNECTION,
    CONF_DEVICE,
    CONF_FHTID,
    CONN_SERIAL,
    DEFAULT_BAUDRATE,
    DEFAULT_TIMEOUT,
    DOMAIN,
    EVENT_COMMAND_FAILED,
    EVENT_FHT_PAIR_FAILED,
    EVENT_FHT_PAIRED,
    OPT_TIME_SYNC,
    OPT_TIMEOUT,
    PAIR_TIMEOUT,
    STORAGE_VERSION,
    signal_cul,
    signal_new,
    signal_update,
)
from .culpy.cul import Cul, CulState
from .culpy.protocols.base import DeviceEvent
from .culpy.protocols.fht import (
    NO_ACK_KEYS,
    SCHEDULE_KEYS,
    encode_value,
    refresh_items,
    time_items,
)
from .culpy.sendqueue import FhtSendQueue
from .culpy.transport.base import Transport
from .culpy.transport.serial import SerialTransport
from .culpy.transport.tcp import TcpTransport

_LOGGER = logging.getLogger(__name__)
PUMP_INTERVAL = timedelta(seconds=10)
TICK_INTERVAL = timedelta(seconds=60)


def create_transport(data: Mapping[str, Any]) -> Transport:
    """Entries from before 0.1.0b2 have no connection type: they are TCP."""
    if data.get(CONF_CONNECTION) == CONN_SERIAL:
        return SerialTransport(data[CONF_DEVICE], data.get(CONF_BAUDRATE, DEFAULT_BAUDRATE))
    return TcpTransport(data[CONF_HOST], data[CONF_PORT])


def fht_code_display(address: str) -> str:
    """The FHT80b shows code 1 and 2 as decimal numbers, one per byte: 1c50 is "028 080"."""
    return f"{int(address[:2], 16):03d} {int(address[2:], 16):03d}"


def fht_code_from_parts(code1: int, code2: int) -> str:
    return f"{code1:02x}{code2:02x}"


@dataclass
class DeviceState:
    protocol: str
    address: str
    values: dict[str, Any] = field(default_factory=dict)
    last_seen: float | None = None

    @property
    def key(self) -> str:
        return f"{self.protocol}:{self.address}"


def _to_json(values: dict[str, Any]) -> dict[str, Any]:
    return {k: (v.strftime("%H:%M") if isinstance(v, time) else v) for k, v in values.items()}


def _from_json(values: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in values.items():
        if k in SCHEDULE_KEYS and isinstance(v, str):
            hh, mm = v.split(":")
            out[k] = time(int(hh), int(mm))
        else:
            out[k] = v
    return out


class CulHub:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass, self.entry = hass, entry
        self.devices: dict[str, DeviceState] = {}
        self.requested: dict[tuple[str, str], Any] = {}
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._unsubs: list = []
        # serialises pumps: a second pump waits, then finds nothing unsent (no double send)
        self._pump_lock = asyncio.Lock()
        # address -> deadline; pairing FHTs get commands although never heard
        self._pairing: dict[str, float] = {}
        self._pair_waiters: dict[str, list[asyncio.Future[bool]]] = {}
        data = dict(entry.data)
        self.cul = Cul(
            lambda: create_transport(data),
            fhtid=entry.data[CONF_FHTID],
            on_event=self._on_event,
            on_state=self._on_state,
        )
        self.queue = FhtSendQueue(self.cul, can_send=self._can_send)

    @property
    def timeout(self) -> int:
        return self.entry.options.get(OPT_TIMEOUT, DEFAULT_TIMEOUT)

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        for d in data.get("devices", []):
            ds = DeviceState(d["protocol"], d["address"], _from_json(d.get("values", {})), d.get("last_seen"))
            self.devices[ds.key] = ds

    def _save_data(self) -> dict[str, Any]:
        return {"devices": [
            {"protocol": d.protocol, "address": d.address, "values": _to_json(d.values), "last_seen": d.last_seen}
            for d in self.devices.values()
        ]}

    @callback
    def async_register_cul_device(self) -> None:
        """Must run before the platforms load, so CUL entities get the device name."""
        dr.async_get(self.hass).async_get_or_create(
            config_entry_id=self.entry.entry_id,
            identifiers={(DOMAIN, f"cul:{self.entry.unique_id}")},
            name=f"CUL {self.entry.unique_id}",
            manufacturer="busware",
            model="CUL",
        )

    async def async_start(self) -> None:
        await self.cul.start()
        self._unsubs.append(async_track_time_interval(self.hass, self._async_pump_tick, PUMP_INTERVAL))
        self._unsubs.append(async_track_time_interval(self.hass, self._async_tick, TICK_INTERVAL))
        if self.entry.options.get(OPT_TIME_SYNC, True):
            self._unsubs.append(
                async_track_time_change(self.hass, self._async_time_sync, hour=4, minute=0, second=0))

    async def async_stop(self) -> None:
        for address in list(self._pair_waiters):
            self._async_pair_done(address, False)
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        await self.cul.stop()
        await self._store.async_save(self._save_data())

    @callback
    def ensure_device(self, protocol: str, address: str) -> DeviceState:
        key = f"{protocol}:{address}"
        if key not in self.devices:
            self.devices[key] = DeviceState(protocol, address)
            async_dispatcher_send(self.hass, signal_new(self.entry.entry_id), self.devices[key])
            self._store.async_delay_save(self._save_data, 10)
        return self.devices[key]

    @callback
    def _on_event(self, event: DeviceEvent) -> None:
        key = f"{event.protocol}:{event.address}"
        if key not in self.devices and all(k.startswith("unknown_") for k in event.values):
            # a corrupt frame must not create a permanent device
            _LOGGER.debug("Ignoring unknown-only event from new device %s: %s", key, event.values)
            return
        device = self.ensure_device(event.protocol, event.address)
        device.values.update(event.values)
        device.last_seen = _time.time()
        # Paired only when the FHT confirms our report request: an FHT80b in CEnt "nA"
        # keeps talking to its actuator, so any telegram is no proof.
        # After last_seen: the pump starts eagerly and checks _can_send right away.
        if (event.protocol == "fht" and event.address in self._pairing
                and ("report1" in event.values or "report2" in event.values)):
            del self._pairing[event.address]
            self._async_paired(event.address)
        for key in self.queue.on_event(event):
            self.requested.pop((event.address, key), None)
        self._store.async_delay_save(self._save_data, 10)
        async_dispatcher_send(self.hass, signal_update(self.entry.entry_id, device.key))

    @callback
    def async_remove_device(self, key: str) -> None:
        if self.devices.pop(key, None) is not None:
            self._store.async_delay_save(self._save_data, 10)

    @callback
    def _on_state(self, state: CulState) -> None:
        async_dispatcher_send(self.hass, signal_cul(self.entry.entry_id))

    def submit(self, address: str, values: dict[str, Any]) -> None:
        items = [(key, encode_value(key, value)) for key, value in values.items()]
        self.queue.submit(address, items)
        for key, value in values.items():
            self.requested[(address, key)] = value
        async_dispatcher_send(self.hass, signal_update(self.entry.entry_id, f"fht:{address}"))
        self.entry.async_create_background_task(self.hass, self._async_pump(), "cul pump")

    def display_value(self, device: DeviceState, key: str) -> Any:
        if (device.address, key) in self.requested:
            return self.requested[(device.address, key)]
        return device.values.get(key)

    def is_pending(self, address: str, key: str) -> bool:
        return (address, key) in self.requested

    def is_available(self, device: DeviceState) -> bool:
        return device.last_seen is not None and _time.time() - device.last_seen < self.timeout

    def _can_send(self, address: str) -> bool:
        """Only send to FHTs heard recently: culfw holds commands until the FHT picks them up.

        Exception: an FHT80b being paired has never been heard.
        """
        if address in self._pairing:
            return True
        device = self.devices.get(f"fht:{address}")
        return device is not None and self.is_available(device)

    def is_pairing(self, address: str) -> bool:
        return address in self._pairing

    @callback
    def async_pair(self, address: str) -> None:
        """Send a report request to an FHT80b in CEnt "nA"; culfw holds it until picked up.

        Sent once: culfw keeps FHT commands until the FHT takes them, a resend would only
        queue a second request in the CUL buffer.
        """
        self.ensure_device("fht", address)
        self._pairing[address] = _time.time() + PAIR_TIMEOUT
        _LOGGER.info("Pairing FHT %s (code %s on the device)", address, fht_code_display(address))
        self.submit(address, dict(refresh_items()))

    async def async_wait_paired(self, address: str) -> bool:
        """True once the FHT answered, False after the pairing timeout."""
        if address not in self._pairing:
            return False
        fut: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._pair_waiters.setdefault(address, []).append(fut)
        return await fut

    @callback
    def _async_pair_done(self, address: str, paired: bool) -> None:
        for fut in self._pair_waiters.pop(address, []):
            if not fut.done():
                fut.set_result(paired)

    @callback
    def _async_paired(self, address: str) -> None:
        _LOGGER.info("FHT %s answered: paired", address)
        self.hass.bus.async_fire(EVENT_FHT_PAIRED, {"address": address})
        persistent_notification.async_create(
            self.hass,
            f"FHT80b {address} (code {fht_code_display(address)}) answered and is paired. "
            "CEnt on the device shows On. Its values arrive within the next minutes.",
            title="CUL: FHT80b paired",
            notification_id=f"{DOMAIN}_pair_{address}",
        )
        self.submit(address, dict(time_items(dt_util.now())))
        self._async_pair_done(address, True)

    @callback
    def _async_pair_tick(self) -> None:
        now = _time.time()
        for address, deadline in list(self._pairing.items()):
            if now < deadline:
                continue
            del self._pairing[address]
            _LOGGER.warning("FHT %s did not answer the pairing request", address)
            self.hass.bus.async_fire(EVENT_FHT_PAIR_FAILED, {"address": address})
            persistent_notification.async_create(
                self.hass,
                f"FHT80b {address} (code {fht_code_display(address)}) did not answer within "
                f"{PAIR_TIMEOUT // 60} min. Check the code and set CEnt to nA on the device. "
                "If old commands for this FHT are stuck in the CUL, restart the CUL "
                "(button on the CUL device), then start pairing again.",
                title="CUL: FHT80b pairing failed",
                notification_id=f"{DOMAIN}_pair_{address}",
            )
            self._async_pair_done(address, False)

    async def async_restart_cul(self) -> None:
        """B00 reboots the CUL; the connection loop reconnects and initialises it again.

        This also clears the FHT buffer in the CUL.
        """
        await self.cul.write("B00")

    async def send_raw(self, line: str) -> None:
        await self.cul.write(line)

    async def _async_pump(self) -> None:
        async with self._pump_lock:
            try:
                while await self.queue.pump():
                    pass
            except (ConnectionError, OSError, TimeoutError) as err:
                _LOGGER.debug("Pump skipped: %s", err)
            # keys without confirmation (report*, clock) are done once sent
            for address, key in list(self.requested):
                if key in NO_ACK_KEYS and key not in self.queue.pending_for(address):
                    del self.requested[(address, key)]

    async def _async_pump_tick(self, _now) -> None:
        await self._async_pump()
        for failed in self.queue.expire():
            value = self.requested.pop((failed.address, failed.key), failed.value)
            self.hass.bus.async_fire(EVENT_COMMAND_FAILED, {
                "address": failed.address, "key": failed.key, "value": value})
            async_dispatcher_send(self.hass, signal_update(self.entry.entry_id, f"fht:{failed.address}"))

    async def _async_tick(self, _now) -> None:
        self._async_pair_tick()
        for device in self.devices.values():
            async_dispatcher_send(self.hass, signal_update(self.entry.entry_id, device.key))

    async def _async_time_sync(self, _now) -> None:
        now = dt_util.now()
        for device in self.devices.values():
            if device.protocol == "fht" and self.is_available(device):
                self.submit(device.address, dict(time_items(now)))
