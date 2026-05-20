"""Multi-currency FX tests (§5.3)."""
from __future__ import annotations

from datetime import date

import pytest

from backend.fx import FXService, get_fx_service
from backend.parsers import parse_with_registry
from tests.conftest import f


def test_cad_is_exactly_one():
    svc = FXService(live_enabled=False)
    assert svc.rate_to_cad("CAD", date(2024, 6, 1)) == 1.0


def test_fx_static_table_complete():
    svc = FXService(live_enabled=False)
    for cur in ["CAD", "USD", "GBP", "EUR", "JPY", "AUD", "CHF", "HKD", "SEK", "NOK"]:
        rate = svc.rate_to_cad(cur, date(2024, 6, 1))
        assert rate > 0, f"Missing rate for {cur}"


def test_fx_usd_to_cad_range():
    svc = FXService(live_enabled=False)
    rate = svc.rate_to_cad("USD", date(2024, 6, 1))
    assert 1.20 <= rate <= 1.50


def test_fx_gbp_higher_than_usd():
    svc = FXService(live_enabled=False)
    assert svc.rate_to_cad("GBP", date(2024, 6, 1)) > svc.rate_to_cad("USD", date(2024, 6, 1))


def test_fx_jpy_below_one():
    svc = FXService(live_enabled=False)
    assert svc.rate_to_cad("JPY", date(2024, 6, 1)) < 0.02


def test_in_file_rate_takes_priority():
    """A rate registered via register_in_file_rate beats the static table."""
    svc = FXService(live_enabled=False)
    svc.register_in_file_rate("USD", date(2024, 7, 15), 1.42)
    assert svc.rate_to_cad("USD", date(2024, 7, 15)) == 1.42
    # Other dates still use the static table
    assert svc.rate_to_cad("USD", date(2024, 1, 1)) != 1.42


def test_convert_to_cad_rounding():
    svc = FXService(live_enabled=False)
    cad = svc.convert_to_cad(100.00, "GBP", date(2024, 6, 1))
    # 100 * 1.72 = 172.00
    assert cad == 172.00


def test_cad_net_populated_for_fidelity_with_no_fx_column():
    """Fidelity CSVs have no FX column — FXService must fill net_cad."""
    result = parse_with_registry(f("Fidelity_2024.csv"))
    assert all(t.net_cad is not None for t in result.transactions)
    assert all(t.fx_rate_to_cad is not None for t in result.transactions)


def test_in_file_fx_rate_priority_for_rbc():
    """RBC carries Exchange Rate + Net CAD Equivalent columns. Those rates
    must show up on the Transaction (and beat the static table when present)."""
    result = parse_with_registry(f("RBC_DirectInvesting_2024.csv"))
    usd_txs = [t for t in result.transactions if t.currency == "USD"]
    assert usd_txs
    for t in usd_txs:
        assert t.fx_rate_to_cad is not None
        assert t.net_cad is not None


def test_singleton_identity():
    assert get_fx_service() is get_fx_service()
