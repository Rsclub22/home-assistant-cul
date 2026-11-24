"""Tests for the FHT80TF window contact."""

from custom_components.cul.culpy.frame import Frame
from custom_components.cul.culpy.protocols.fhttk import FhtTkProtocol


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def f(payload):
    return Frame("T", payload, -60.0)


def test_accepts():
    p = FhtTkProtocol()
    assert p.accepts(f("B1987B02"))
    assert not p.accepts(f("1C50002633"))


def test_unknown_state_not_accepted():
    p = FhtTkProtocol()
    assert not p.accepts(f("B1987B55"))
    assert not p.accepts(f("1C500026"))  # FHT frame without RSSI byte: 'T1C50002633'
    assert p.accepts(f("B1987B8C")) and p.accepts(f("B1987B0F"))


def test_states():
    p = FhtTkProtocol(Clock())
    assert p.decode(f("B1987B02")).values == {"window-open": False, "battery-low": False}
    assert p.decode(f("B1987B81")).values == {"window-open": True, "battery-low": False}
    assert p.decode(f("B1987B92")).values == {"window-open": False, "battery-low": True}
    assert p.decode(f("B1987B11")).values == {"window-open": True, "battery-low": True}
    assert p.decode(f("B1987B0C")).values == {"sync": True}
    assert p.decode(f("B1987B0F")).values == {"test": True}


def test_address_lower():
    ev = FhtTkProtocol().decode(f("B1987B02"))
    assert (ev.protocol, ev.address) == ("fhttk", "b1987b")


def test_duplicate_within_5s_ignored():
    clock = Clock()
    p = FhtTkProtocol(clock)
    assert p.decode(f("B1987B01")) is not None
    clock.now += 2
    assert p.decode(f("B1987B81")) is None  # 81 == 01 (same state)
    clock.now += 4
    assert p.decode(f("B1987B01")) is not None
    assert p.decode(f("B1987B02")) is not None  # change is never suppressed
