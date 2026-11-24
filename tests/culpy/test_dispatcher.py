"""Tests for the protocol dispatcher."""

from custom_components.cul.culpy.frame import Frame
from custom_components.cul.culpy.protocols.base import Dispatcher
from custom_components.cul.culpy.protocols.fht import FhtProtocol


def test_dispatch_known_and_unknown():
    d = Dispatcher([FhtProtocol()])
    assert d.dispatch(Frame("T", "1C50416928", None)).values == {"desired-temp": 20.0}
    assert d.dispatch(Frame("T", "1C504269C4", None)) is None  # accepted, no event yet
    assert d.dropped == 0
    assert d.dispatch(Frame("K", "1234567890", None)) is None
    assert d.dropped == 1
