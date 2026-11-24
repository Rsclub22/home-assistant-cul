"""FHT80TF window contact (culfw 'T' messages with 6-digit address)."""

from __future__ import annotations

import time
from collections.abc import Callable

from ..frame import Frame
from .base import DeviceEvent

# state byte → (window_open, battery_low); 0x8x is the same state as 0x0x
_STATES = {
    0x01: (True, False),
    0x02: (False, False),
    0x11: (True, True),
    0x12: (False, True),
}
_KNOWN = set(_STATES) | {0x0C, 0x0F}  # + sync, test
DUPLICATE_WINDOW = 5.0


def _canonical(state: int) -> int:
    return state & 0x7F if state & 0x80 else state


class FhtTkProtocol:
    name = "fhttk"

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._last: dict[str, tuple[int, float]] = {}

    def accepts(self, frame: Frame) -> bool:
        # Unknown state bytes are rejected (counted as dropped): an FHT frame without its
        # RSSI byte (T1C50002633) also has 8 digits and would become a phantom FHT80TF.
        return (frame.kind == "T" and len(frame.payload) == 8
                and _canonical(int(frame.payload[6:8], 16)) in _KNOWN)

    def decode(self, frame: Frame) -> DeviceEvent | None:
        address = frame.payload[0:6].lower()
        state = _canonical(int(frame.payload[6:8], 16))
        now = self._clock()
        last = self._last.get(address)
        if last and last[0] == state and now - last[1] < DUPLICATE_WINDOW:
            return None
        self._last[address] = (state, now)
        if state in _STATES:
            window_open, battery_low = _STATES[state]
            values = {"window-open": window_open, "battery-low": battery_low}
        elif state == 0x0C:
            values = {"sync": True}
        else:  # 0x0F, accepts() lets only known states through
            values = {"test": True}
        return DeviceEvent("fhttk", address, values, frame.rssi)
