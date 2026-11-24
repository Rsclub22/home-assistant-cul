"""Split culfw output lines into RF frames."""

from __future__ import annotations

import re
from dataclasses import dataclass

# culfw with X21 appends one RSSI byte (two hex digits) to every RF message.
RF_RE = re.compile(r"^[AFTKEHRStZrib](?:[A-F0-9]{2})+$")


@dataclass(frozen=True, slots=True)
class Frame:
    """One RF message from the CUL, RSSI byte removed."""

    kind: str
    payload: str
    rssi: float | None


def rssi_from_byte(value: int) -> float:
    """Convert the culfw RSSI byte to dBm."""
    return (value - 256) / 2 - 74 if value >= 128 else value / 2 - 74


def parse_rf_line(line: str) -> Frame | None:
    """Return a Frame for RF lines, None for anything else (answers, LOVF, garbage)."""
    line = line.strip()
    if not RF_RE.match(line):
        return None
    return Frame(kind=line[0], payload=line[1:-2], rssi=rssi_from_byte(int(line[-2:], 16)))
