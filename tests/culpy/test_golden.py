"""Compare culpy decoding with FHEM readings from a real recording."""

import json
from pathlib import Path

import pytest

from custom_components.cul.culpy.frame import parse_rf_line
from custom_components.cul.culpy.protocols.fht import SCHEDULE_KEYS, FhtProtocol
from custom_components.cul.culpy.protocols.fhttk import FhtTkProtocol
from custom_components.cul.sensor import _warnings_text  # FHEM-Text kommt aus der HA-Schicht

FIXTURE = Path(__file__).parent / "fixtures" / "golden.jsonl"


def fhem_format(values: dict) -> dict[str, str]:
    out = {}
    for key, v in values.items():
        if key.endswith(("-status", "-offset", "-synctime")):
            continue
        if key.startswith("actuator"):
            st = values[f"{key}-status"]
            out[key] = (f"{v}%" if st in ("ok", "on", "off") else
                        f"offset: {values[f'{key}-offset']}" if st == "offset" else
                        f"synctime: {values[f'{key}-synctime']}" if st == "synctime" else st)
        elif key == "desired-temp":
            out[key] = "on" if v > 30 else "off" if v < 6 else f"{v:.1f}"
        elif key.endswith("-temp"):
            out[key] = f"{v:.1f}"
        elif key == "lowtemp-offset":
            out[key] = f"{v}.0"
        elif key in SCHEDULE_KEYS:
            out[key] = "24:00" if v is None else v.strftime("%H:%M")
        elif key == "window-open":
            out["Window"] = "Open" if v else "Closed"
        elif key == "warnings":
            out[key] = _warnings_text(v)
        elif key == "battery-low":
            out["batteryState"] = "low" if v else "ok"
        elif isinstance(v, bool):
            continue
        else:
            out[key] = str(v)
    return out


@pytest.mark.skipif(not FIXTURE.exists(), reason="no FHEM recording yet")
def test_golden():
    fht, tk = FhtProtocol(), FhtTkProtocol(clock=lambda: 0.0)
    mismatches, checked = [], 0
    for n, line in enumerate(FIXTURE.read_text().splitlines()):
        row = json.loads(line)
        frame = parse_rf_line(row["raw"])
        proto = fht if fht.accepts(frame) else tk
        if proto is tk:
            tk._last.clear()  # FHEM already de-duplicated what it logged
        event = proto.decode(frame)
        if event is None:
            continue
        ours = fhem_format(event.values)
        for reading, fhem_value in row["readings"].items():
            if reading in ours:
                checked += 1
                if ours[reading] != fhem_value:
                    mismatches.append((n, row["raw"], reading, fhem_value, ours[reading]))
    assert checked > 0
    assert mismatches == []
