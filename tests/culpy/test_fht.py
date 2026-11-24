"""Tests for the FHT80b protocol module."""

from datetime import datetime, time

import pytest

from custom_components.cul.culpy.frame import Frame
from custom_components.cul.culpy.protocols.fht import (
    SCHEDULE_KEYS,
    FhtProtocol,
    encode_command,
    encode_value,
    holiday_items,
    refresh_items,
    time_items,
)


def frame(payload: str) -> Frame:
    return Frame("T", payload, -50.0)


def decode(payload: str, proto: FhtProtocol | None = None):
    proto = proto or FhtProtocol()
    return proto.decode(frame(payload))


def test_accepts_only_fht_length():
    proto = FhtProtocol()
    assert proto.accepts(frame("1C50002633"))
    assert not proto.accepts(frame("B1987B02"))
    assert not proto.accepts(Frame("F", "1C50002633", None))


def test_desired_temp():
    ev = decode("1C50416928")
    assert (ev.protocol, ev.address, ev.values) == ("fht", "1c50", {"desired-temp": 20.0})
    assert ev.rssi == -50.0


def test_actuator_percent():
    assert decode("1C50002633").values == {"actuator": 20, "actuator-status": "ok"}


@pytest.mark.parametrize(
    ("status", "val", "expected"),
    [
        ("A0", "FF", {"actuator": 100, "actuator-status": "ok"}),
        ("20", "00", {"actuator": None, "actuator-status": "syncnow"}),
        ("21", "00", {"actuator": 99, "actuator-status": "on"}),
        ("22", "00", {"actuator": 0, "actuator-status": "off"}),
        ("28", "85", {"actuator": None, "actuator-status": "offset", "actuator-offset": -5}),
        ("28", "05", {"actuator": None, "actuator-status": "offset", "actuator-offset": 5}),
        ("2A", "00", {"actuator": None, "actuator-status": "lime-protection"}),
        ("AA", "80", {"actuator": 50, "actuator-status": "ok"}),
        ("2C", "08", {"actuator": None, "actuator-status": "synctime", "actuator-synctime": 3}),
        ("2E", "00", {"actuator": None, "actuator-status": "test"}),
        ("2F", "00", {"actuator": None, "actuator-status": "pair"}),
        ("23", "40", {"actuator": 25, "actuator-status": "unknown"}),
    ],
)
def test_actuator_status(status, val, expected):
    assert decode(f"1C5000{status}{val}").values == expected


def test_actuator1():
    assert decode("1C50012680").values == {"actuator1": 50, "actuator1-status": "ok"}


def test_measured_temp_needs_low_then_high():
    proto = FhtProtocol()
    assert decode("1C504269C4", proto) is None
    assert decode("1C50436900", proto).values == {"measured-temp": 19.6}
    assert decode("1C50436900", proto) is None  # high without new low


def test_measured_low_is_per_device():
    proto = FhtProtocol()
    decode("1C504269C4", proto)
    assert decode("0E52436900", proto) is None


def test_schedule_times():
    assert decode("1C50146924").values == {"mon-from1": time(6, 0)}
    assert decode("1C502F6990").values == {"sun-to2": None}
    assert decode("1C50156927").values == {"mon-to1": time(6, 30)}


def test_schedule_key_order():
    assert SCHEDULE_KEYS[:4] == ("mon-from1", "mon-to1", "mon-from2", "mon-to2")
    assert SCHEDULE_KEYS[-1] == "sun-to2"
    assert len(SCHEDULE_KEYS) == 28


def test_mode():
    assert decode("1C503E6901").values == {"mode": "manual"}
    assert decode("1C503E6903").values == {"mode": "holiday_short"}


def test_warnings():
    assert decode("1C50446921").values == {
        "warnings": 33,
        "battery-low": True,
        "lowtemp": False,
        "window-open": True,
        "windowsensor-fault": False,
    }


def test_other_temps_and_ints():
    assert decode("1C50826928").values == {"day-temp": 20.0}
    assert decode("1C50846922").values == {"night-temp": 17.0}
    assert decode("1C508A690C").values == {"windowopen-temp": 6.0}
    assert decode("1C50856902").values == {"lowtemp-offset": 2}
    assert decode("1C50606919").values == {"year": 25}
    assert decode("1C504B6900").values == {"ack": 0}


def test_unknown_code():
    assert decode("1C50996907").values == {"unknown_99": 7}


def test_encode_desired_temp():
    assert encode_command("1c50", [("desired-temp", encode_value("desired-temp", 20.0))]) == (
        "T1C504128"
    )


def test_encode_values():
    assert encode_value("desired-temp", 20.25) == 40
    assert encode_value("desired-temp", 5.5) == 11
    assert encode_value("mon-from1", time(6, 35)) == 39
    assert encode_value("mon-from1", None) == 144
    assert encode_value("mode", "holiday") == 2
    assert encode_value("lowtemp-offset", 3) == 3
    assert encode_value("holiday1", 24) == 24


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("desired-temp", 31.0),
        ("day-temp", 5.0),
        ("mode", "party"),
        ("lowtemp-offset", 6),
        ("holiday1", 256),
        ("actuator", 10),
        ("measured-temp", 20.0),
    ],
)
def test_encode_rejects(key, value):
    with pytest.raises(ValueError):
        encode_value(key, value)


def test_encode_command_limits():
    with pytest.raises(ValueError):
        encode_command("1c50", [])
    with pytest.raises(ValueError):
        encode_command("1c50", [("holiday1", 1)] * 9)


def test_helper_items():
    assert time_items(datetime(2026, 11, 21, 4, 0, 0)) == [
        ("year", 26),
        ("month", 11),
        ("day", 21),
        ("hour", 4),
        ("minute", 0),
    ]
    assert refresh_items() == [("report1", 255), ("report2", 255)]
    assert holiday_items("holiday", datetime(2026, 12, 24, 0, 0), 15.0) == [
        ("mode", "holiday"),
        ("holiday1", 24),
        ("holiday2", 12),
        ("desired-temp", 15.0),
    ]
    assert holiday_items("holiday_short", datetime(2026, 11, 22, 6, 30), 15.0) == [
        ("mode", "holiday_short"),
        ("holiday1", 39),
        ("holiday2", 22),
        ("desired-temp", 15.0),
    ]
    with pytest.raises(ValueError):
        holiday_items("auto", datetime(2026, 11, 22), 15.0)
