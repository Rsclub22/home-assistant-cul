"""FHT send queue: coalescing, priorities, CUL buffer check, LOVF pause, ack tracking."""

from __future__ import annotations

import itertools
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from .cul import Cul
from .protocols.base import DeviceEvent
from .protocols.fht import NO_ACK_KEYS, PRIORITY, encode_command, encode_value

_LOGGER = logging.getLogger(__name__)
MAX_ITEMS = 8
LOW_BUFFER = 5  # 3 bytes header + 2 per item: below this not even one item fits
LOW_BUFFER_WARN_AFTER = 600.0


@dataclass
class _Pending:
    value: int
    priority: int
    submitted: float
    order: int
    sent: float | None = None


@dataclass(frozen=True, slots=True)
class CommandFailed:
    address: str
    key: str
    value: int


class FhtSendQueue:
    def __init__(
        self,
        cul: Cul,
        *,
        clock: Callable[[], float] = time.monotonic,
        ack_timeout: float = 900.0,
        lovf_pause: float = 60.0,
        can_send: Callable[[str], bool] = lambda address: True,
    ) -> None:
        self._cul, self._clock = cul, clock
        # culfw keeps FHT commands until the FHT takes them in its send window: commands
        # for a silent device would fill the buffer, so such addresses wait here instead.
        self._can_send = can_send
        self._low_since: float | None = None
        self._low_warned = False
        self._ack_timeout, self._lovf_pause = ack_timeout, lovf_pause
        self._pending: dict[tuple[str, str], _Pending] = {}
        self._resume_at = 0.0
        self._counter = itertools.count()

    def submit(self, address: str, items: list[tuple[str, int]]) -> None:
        """Values already encoded. Same priority keeps submit order (schedule from1, to1, …)."""
        now = self._clock()
        for key, value in items:
            self._pending[(address, key)] = _Pending(
                value, PRIORITY.get(key, 9), now, next(self._counter))

    def pending_for(self, address: str) -> dict[str, int]:
        return {k: p.value for (a, k), p in self._pending.items() if a == address}

    async def pump(self) -> bool:
        if not self._cul.state.connected or self._clock() < self._resume_at:
            return False
        if self._cul.state.lovf:
            # A real LOVF line arrived: pause before refresh_status() can clear the flag.
            self._cul.state.lovf = False
            self._resume_at = self._clock() + self._lovf_pause
            _LOGGER.warning("CUL send limit reached (LOVF), pausing %.0f s", self._lovf_pause)
            return False
        unsent: dict[str, list[tuple[int, int, str, _Pending]]] = {}
        for (address, key), p in self._pending.items():
            if p.sent is None and self._can_send(address):
                unsent.setdefault(address, []).append((p.priority, p.order, key, p))
        if not unsent:
            return False
        try:
            await self._cul.refresh_status()
        except (ConnectionError, TimeoutError) as err:
            _LOGGER.debug("Status query failed: %s", err)
            return False
        if self._cul.state.lovf:
            self._resume_at = self._clock() + self._lovf_pause
            _LOGGER.warning("CUL send limit reached (LOVF), pausing %.0f s", self._lovf_pause)
            return False
        fits = ((self._cul.state.fhtbuf or 0) - 3) // 2
        self._check_low_buffer(fits)
        if fits < 1:
            return False
        # oldest/most urgent address first; every item costs the same, so whatever does not
        # fit is shrunk to what fits and the rest waits for the next pump
        address, entries = min(unsent.items(), key=lambda kv: min(e[:2] for e in kv[1]))
        entries.sort()
        batch = [(key, p) for _, _, key, p in entries[:min(MAX_ITEMS, fits)]]
        await self._cul.write(encode_command(address, [(key, p.value) for key, p in batch]))
        now = self._clock()
        for key, p in batch:
            # Only touch entries that are still the very object we sent: a newer submit,
            # an ack or an expiry may have replaced or removed it while we awaited.
            if self._pending.get((address, key)) is not p:
                continue
            if key in NO_ACK_KEYS:
                del self._pending[(address, key)]
            else:
                p.sent = now
        return True

    def _check_low_buffer(self, fits: int) -> None:
        if fits >= 1:
            self._low_since, self._low_warned = None, False
            return
        now = self._clock()
        if self._low_since is None:
            self._low_since = now
        elif not self._low_warned and now - self._low_since > LOW_BUFFER_WARN_AFTER:
            self._low_warned = True
            _LOGGER.warning(
                "CUL FHT buffer below %d bytes for over %.0f s: FHT commands cannot be sent",
                LOW_BUFFER, LOW_BUFFER_WARN_AFTER)

    def on_event(self, event: DeviceEvent) -> list[str]:
        if event.protocol != "fht":
            return []
        confirmed = []
        for key, decoded in event.values.items():
            p = self._pending.get((event.address, key))
            if p is None:
                continue
            try:
                matches = encode_value(key, decoded) == p.value
            except ValueError:
                matches = False
            if matches:
                del self._pending[(event.address, key)]
                confirmed.append(key)
        return confirmed

    def expire(self) -> list[CommandFailed]:
        now = self._clock()
        failed = [
            CommandFailed(address, key, p.value)
            for (address, key), p in self._pending.items()
            if now - p.submitted > self._ack_timeout
        ]
        for f in failed:
            del self._pending[(f.address, f.key)]
            _LOGGER.warning("FHT %s: %s=%s not confirmed", f.address, f.key, f.value)
        return failed
