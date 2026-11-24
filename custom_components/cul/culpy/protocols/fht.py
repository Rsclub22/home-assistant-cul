"""FHT80b protocol (culfw 'T' messages with 4-digit housecode)."""

from __future__ import annotations

from datetime import datetime, time
from typing import Any

from ..frame import Frame
from .base import DeviceEvent

_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
SCHEDULE_KEYS: tuple[str, ...] = tuple(
    f"{day}-{part}" for day in _DAYS for part in ("from1", "to1", "from2", "to2")
)

CODES: dict[int, str] = {0x00: "actuator"}
CODES.update({i: f"actuator{i}" for i in range(1, 9)})
CODES.update({0x14 + i: key for i, key in enumerate(SCHEDULE_KEYS)})
CODES.update(
    {
        0x3E: "mode",
        0x3F: "holiday1",
        0x40: "holiday2",
        0x41: "desired-temp",
        0x42: "measured-low",
        0x43: "measured-high",
        0x44: "warnings",
        0x45: "manu-temp",
        0x4B: "ack",
        0x53: "can-xmit",
        0x54: "can-rcv",
        0x60: "year",
        0x61: "month",
        0x62: "day",
        0x63: "hour",
        0x64: "minute",
        0x65: "report1",
        0x66: "report2",
        0x69: "ack2",
        0x7D: "start-xmit",
        0x7E: "end-xmit",
        0x82: "day-temp",
        0x84: "night-temp",
        0x85: "lowtemp-offset",
        0x8A: "windowopen-temp",
    }
)
KEY_TO_CODE: dict[str, int] = {v: k for k, v in CODES.items()}

_READ_ONLY = {
    "ack", "ack2", "can-xmit", "can-rcv", "start-xmit", "end-xmit",
    "measured-low", "measured-high", "warnings",
} | {k for k in KEY_TO_CODE if k.startswith("actuator")}
SETTABLE_KEYS: frozenset[str] = frozenset(set(KEY_TO_CODE) - _READ_ONLY)
NO_ACK_KEYS: frozenset[str] = frozenset(
    {"report1", "report2", "year", "month", "day", "hour", "minute"}
)
PRIORITY: dict[str, int] = {
    "minute": 0,
    "desired-temp": 1,
    "mode": 2,
    "report1": 3,
    "report2": 3,
    "holiday1": 4,
    "holiday2": 5,
    "day-temp": 6,
    "night-temp": 7,
}
MODES: dict[int, str] = {0: "auto", 1: "manual", 2: "holiday", 3: "holiday_short"}
_MODE_CODES = {v: k for k, v in MODES.items()}
TIME_UNUSED = 144  # 24:00 = slot not used


def _decode_time(val: int) -> time | None:
    if val >= TIME_UNUSED:
        return None
    return time(val // 6, (val % 6) * 10)


def _decode_actuator(key: str, status: int, val: int) -> dict[str, Any]:
    pct = int(100 * val / 255 + 0.5)
    low, high = status & 0x0F, status >> 4
    out: dict[str, Any]
    if status in (0xA0, 0xB0) or low == 0x6:
        out = {key: pct, f"{key}-status": "ok"}
    elif low == 0x0:
        out = {key: None, f"{key}-status": "syncnow"}
    elif low == 0x1:
        out = {key: 99, f"{key}-status": "on"}
    elif low == 0x2:
        out = {key: 0, f"{key}-status": "off"}
    elif low == 0x8:
        out = {key: None, f"{key}-status": "offset", f"{key}-offset": 128 - val if val > 128 else val}
    elif low == 0xA and high in (0x2, 0x3):
        out = {key: None, f"{key}-status": "lime-protection"}
    elif low == 0xA and high in (0xA, 0xB):
        out = {key: pct, f"{key}-status": "ok"}
    elif low == 0xC:
        out = {key: None, f"{key}-status": "synctime", f"{key}-synctime": int(val / 2) - 1}
    elif low == 0xE:
        out = {key: None, f"{key}-status": "test"}
    elif low == 0xF:
        out = {key: None, f"{key}-status": "pair"}
    else:
        out = {key: pct, f"{key}-status": "unknown"}
    return out


def _decode_warnings(val: int) -> dict[str, Any]:
    return {
        "warnings": val,
        "battery-low": bool(val & 1),
        "lowtemp": bool(val & 2),
        "window-open": bool(val & 32),
        "windowsensor-fault": bool(val & 16),
    }


class FhtProtocol:
    """Decode FHT80b messages: T<code:4><cmd:2><status:2><value:2>."""

    name = "fht"

    def __init__(self) -> None:
        self._measured_low: dict[str, int] = {}

    def accepts(self, frame: Frame) -> bool:
        return frame.kind == "T" and len(frame.payload) == 10

    def decode(self, frame: Frame) -> DeviceEvent | None:
        p = frame.payload
        address = p[0:4].lower()
        cde, status, val = int(p[4:6], 16), int(p[6:8], 16), int(p[8:10], 16)
        key = CODES.get(cde)
        values: dict[str, Any]
        if key is None:
            values = {f"unknown_{cde:02x}": val}
        elif key == "measured-low":
            self._measured_low[address] = val
            return None
        elif key == "measured-high":
            low = self._measured_low.pop(address, None)
            if low is None:
                return None
            values = {"measured-temp": round((val * 256 + low) / 10, 1)}
        elif key in SCHEDULE_KEYS:
            values = {key: _decode_time(val)}
        elif key == "mode":
            values = {key: MODES.get(val, f"unknown_{val}")}
        elif key.endswith("-temp"):
            values = {key: val / 2}
        elif key.startswith("actuator"):
            values = _decode_actuator(key, status, val)
        elif key == "warnings":
            values = _decode_warnings(val)
        else:
            values = {key: val}
        return DeviceEvent("fht", address, values, frame.rssi)


def encode_value(key: str, value: Any) -> int:
    """Python value → FHT byte. Raises ValueError for read-only keys or bad values."""
    if key not in SETTABLE_KEYS:
        raise ValueError(f"{key} is read-only")
    if key in SCHEDULE_KEYS:
        if value is None:
            return TIME_UNUSED
        if not isinstance(value, time):
            raise ValueError(f"{key} needs a datetime.time or None")
        return value.hour * 6 + value.minute // 10
    if key == "mode":
        if value not in _MODE_CODES:
            raise ValueError(f"invalid mode {value}")
        return _MODE_CODES[value]
    if key.endswith("-temp"):
        temp = float(value)
        if not 5.5 <= temp <= 30.5:
            raise ValueError(f"{key} must be between 5.5 and 30.5")
        return int(temp * 2)
    if key == "lowtemp-offset":
        if int(value) != value or not 1 <= int(value) <= 5:
            raise ValueError("lowtemp-offset must be 1..5")
        return int(value)
    if int(value) != value or not 0 <= int(value) <= 255:
        raise ValueError(f"{key} must be 0..255")
    return int(value)


def encode_command(address: str, items: list[tuple[str, int]]) -> str:
    """Build the culfw send line for up to 8 already-encoded values."""
    if not 1 <= len(items) <= 8:
        raise ValueError("an FHT telegram carries 1..8 values")
    body = "".join(f"{KEY_TO_CODE[key]:02X}{val:02X}" for key, val in items)
    return f"T{address.upper()}{body}"


def time_items(now: datetime) -> list[tuple[str, Any]]:
    return [
        ("year", now.year - 2000),
        ("month", now.month),
        ("day", now.day),
        ("hour", now.hour),
        ("minute", now.minute),
    ]


def refresh_items() -> list[tuple[str, Any]]:
    return [("report1", 255), ("report2", 255)]


def holiday_items(mode: str, end: datetime, temperature: float) -> list[tuple[str, Any]]:
    """holiday: holiday1=end day, holiday2=end month; holiday_short: holiday1=end time
    in 10-min steps, holiday2=end day. All must go out in one telegram."""
    if mode == "holiday":
        h1, h2 = end.day, end.month
    elif mode == "holiday_short":
        h1, h2 = end.hour * 6 + end.minute // 10, end.day
    else:
        raise ValueError("mode must be holiday or holiday_short")
    return [("mode", mode), ("holiday1", h1), ("holiday2", h2), ("desired-temp", temperature)]
