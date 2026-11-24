"""Tests for culpy.frame."""

import pytest

from custom_components.cul.culpy.frame import Frame, parse_rf_line, rssi_from_byte


def test_fht_line_with_rssi():
    assert parse_rf_line("T1C500026334A\r\n") == Frame("T", "1C50002633", -37.0)


def test_fhttk_line_with_negative_rssi():
    assert parse_rf_line("TB1987B02C8") == Frame("T", "B1987B02", -102.0)


@pytest.mark.parametrize(
    "line", ["", "LOVF", "EOB", "V 1.67 CUL868", "1034", "21  900", "T1C5", "T1C500026334", "t1c50"]
)
def test_non_rf_lines(line):
    assert parse_rf_line(line) is None


def test_rssi_formula():
    assert rssi_from_byte(0) == -74.0
    assert rssi_from_byte(127) == -10.5
    assert rssi_from_byte(128) == -138.0
