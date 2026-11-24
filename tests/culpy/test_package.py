"""culpy package rules."""

from pathlib import Path

from custom_components.cul import culpy

CULPY_DIR = Path(culpy.__file__).parent


def test_version():
    assert culpy.__version__ == "0.1.0"


def test_culpy_has_no_homeassistant_imports():
    offenders = [
        str(p.relative_to(CULPY_DIR))
        for p in CULPY_DIR.rglob("*.py")
        if "homeassistant" in p.read_text(encoding="utf-8")
    ]
    assert offenders == []
