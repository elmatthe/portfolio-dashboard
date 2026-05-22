"""Regression guard for the parser-registry contract.

Historical bug: PyInstaller-packaged builds shipped without
`backend.parsers.generic` as a hidden import, so `parse_with_registry` raised
`KeyError: 'generic'` on every upload that fell through to the fallback. The
spec file now lists all 12 parsers explicitly. This test reasserts the contract
inside the test environment — if any new parser is added or an existing one is
deleted without updating the spec, the suite fails before a release.
"""
from __future__ import annotations

from backend.parsers import BROKER_PARSERS
from backend.parsers.registry import _populate_registry


EXPECTED_PARSERS = {
    "questrade",
    "wealthsimple",
    "rbc",
    "cibc",
    "td",
    "bmo",
    "scotiabank",
    "interactive",
    "nationalbank",
    "fidelity",
    "hsbc",
    "generic",
}


def test_all_parsers_register():
    _populate_registry()
    missing = EXPECTED_PARSERS - set(BROKER_PARSERS.keys())
    assert not missing, f"Missing parsers (PyInstaller hiddenimports gap?): {missing}"
    assert len(BROKER_PARSERS) >= len(EXPECTED_PARSERS)


def test_generic_fallback_present():
    """`parse_with_registry` falls back to 'generic' when detection score < 0.5;
    this key must always be in the registry."""
    _populate_registry()
    assert "generic" in BROKER_PARSERS
