"""Per-broker parser tests (§5.1). One row count + sanity assertions per parser."""
from __future__ import annotations

import pytest

from backend.parsers import BROKER_PARSERS, parse_with_registry
from backend.parsers.registry import _populate_registry
from tests.conftest import f

VALID_CURRENCIES = {"CAD", "USD", "GBP", "EUR", "JPY", "AUD", "CHF", "HKD", "SEK", "NOK"}
VALID_ACTIONS = {"BUY", "SELL", "DIVIDEND", "DEPOSIT", "WITHDRAWAL", "CONTRIBUTION", "FEE", "SPLIT", "INTEREST", "TRANSFER", "OTHER"}


_FIXTURES = [
    ("RBC_DirectInvesting_2024.csv",            "rbc",          42),
    ("CIBC_InvestorsEdge_2024.csv",             "cibc",         38),
    ("TD_DirectInvesting_2024.csv",             "td",           45),
    ("BMO_InvestorLine_2024.csv",               "bmo",          36),
    ("Scotia_iTRADE_2024.csv",                  "scotiabank",   40),
    ("InteractiveBrokers_2024.csv",             "interactive",  50),
    ("NationalBank_DirectBrokerage_2024.csv",   "nationalbank", 35),
    ("Fidelity_2024.csv",                       "fidelity",     40),
    ("BMO_InvestorLine_2024.xlsx",              "bmo",          38),
    ("Scotia_iTRADE_2024.xlsx",                 "scotiabank",   42),
    ("HSBC_InvestDirect_2024.xlsx",             "hsbc",         33),
    ("RBC_DirectInvesting_2024.pdf",            "rbc",          40),
    ("TD_DirectInvesting_2024.pdf",             "td",           35),
    ("CIBC_InvestorsEdge_2024.pdf",             "cibc",         33),
]


@pytest.mark.parametrize("fname,broker_key,expected", _FIXTURES)
def test_parser_row_count(fname, broker_key, expected):
    """Each broker parser produces the expected number of rows."""
    result = parse_with_registry(f(fname))
    assert result.broker_key == broker_key
    assert len(result.transactions) == expected, f"{fname}: got {len(result.transactions)}"


@pytest.mark.parametrize("fname,broker_key,_count", _FIXTURES)
def test_parser_dates_populated(fname, broker_key, _count):
    """Every parsed transaction has a valid trade date."""
    result = parse_with_registry(f(fname))
    assert all(t.transaction_date is not None for t in result.transactions)


@pytest.mark.parametrize("fname,broker_key,_count", _FIXTURES)
def test_parser_actions_valid(fname, broker_key, _count):
    result = parse_with_registry(f(fname))
    assert all(t.action in VALID_ACTIONS for t in result.transactions), f"{fname}"


@pytest.mark.parametrize("fname,broker_key,_count", _FIXTURES)
def test_parser_currencies_valid(fname, broker_key, _count):
    result = parse_with_registry(f(fname))
    assert all(t.currency in VALID_CURRENCIES for t in result.transactions), f"{fname}"


@pytest.mark.parametrize("fname,broker_key,_count", _FIXTURES)
def test_parser_net_cad_populated(fname, broker_key, _count):
    """Every parsed transaction has a CAD equivalent (in-file or FXService)."""
    result = parse_with_registry(f(fname))
    assert all(t.net_cad is not None for t in result.transactions), f"{fname}"


# Regression tests (§5.5)

def test_wealthsimple_regression():
    """REGRESSION: Wealthsimple must parse exactly as before."""
    result = parse_with_registry(f("Wealthsimple_Test_Transactions.csv"))
    assert result.broker_key == "wealthsimple"
    assert len(result.transactions) == 35
    assert all(t.currency in ("CAD", "USD") for t in result.transactions)


def test_questrade_regression():
    """REGRESSION: Questrade must parse exactly as before."""
    result = parse_with_registry(f("Questrade_Test_Transactions.xlsx"))
    assert result.broker_key == "questrade"
    assert len(result.transactions) == 46


# Edge cases (§5.5)

def test_ib_signed_quantity_normalized():
    """IB negative quantities (= BUY) must be normalised to positive."""
    result = parse_with_registry(f("InteractiveBrokers_2024.csv"))
    assert all(t.quantity > 0 for t in result.transactions)
    # Must have at least one BUY to prove the normalisation actually fired.
    assert any(t.action == "BUY" for t in result.transactions)


def test_ib_data_discriminator_filter():
    """IB filter must yield exactly 50 Trade rows (statement metadata excluded)."""
    result = parse_with_registry(f("InteractiveBrokers_2024.csv"))
    assert len(result.transactions) == 50


def test_scotia_dd_mm_yyyy_parsed():
    """Scotia DD/MM/YYYY: every parsed date must be in 2024."""
    result = parse_with_registry(f("Scotia_iTRADE_2024.csv"))
    assert all(t.transaction_date.year == 2024 for t in result.transactions)


def test_fidelity_zero_commission():
    result = parse_with_registry(f("Fidelity_2024.csv"))
    assert all(t.commission == 0.0 for t in result.transactions)


def test_hsbc_isin_captured():
    result = parse_with_registry(f("HSBC_InvestDirect_2024.xlsx"))
    isin_txs = [t for t in result.transactions if t.isin]
    assert len(isin_txs) > 0
    # In the fixture, every HSBC row carries an ISIN.
    assert len(isin_txs) == len(result.transactions)


def test_bmo_xlsx_skips_title_rows():
    """BMO XLSX merged title rows 1-3 must NOT become transactions."""
    result = parse_with_registry(f("BMO_InvestorLine_2024.xlsx"))
    assert len(result.transactions) == 38
    assert all(t.transaction_date.year == 2024 for t in result.transactions)


def test_registry_assembles_all_parsers():
    """All 12 parser modules register on first use."""
    _populate_registry()
    expected = {
        "wealthsimple", "questrade",
        "interactive", "rbc", "cibc", "td", "bmo", "scotiabank",
        "nationalbank", "fidelity", "hsbc", "generic",
    }
    assert expected.issubset(set(BROKER_PARSERS.keys()))
