"""Item 4 Step 4 — row normalization + per-row transaction classification."""
from __future__ import annotations

from datetime import date
from typing import get_args

import pytest

from backend.import_engine.canonical import (
    ACTION_DOWNMAP,
    CanonicalAction,
    CanonicalField as F,
    to_emitted_action,
)
from backend.import_engine.classify_columns import MappingResult
from backend.import_engine.classify_tx import (
    RowState,
    classify_row,
    classify_table,
    infer_action,
)
from backend.import_engine.normalize import normalize_row
from backend.models import Action

_EMITTED = set(get_args(Action))


def _mapping(**fields: int) -> MappingResult:
    """Build a MappingResult from {field_name: column_index}."""
    return MappingResult(mapping={getattr(F, k.upper()): v for k, v in fields.items()})


def _classify(mapping: MappingResult, row: list[str]):
    return classify_row(normalize_row(row, mapping), mapping)


# --------------------------------------------------------------------------- #
# Down-map contract                                                           #
# --------------------------------------------------------------------------- #

def test_every_canonical_action_downmaps_to_a_valid_action():
    for ca in CanonicalAction:
        emitted = to_emitted_action(ca)
        assert emitted in _EMITTED, f"{ca} → {emitted} not a models.Action"
    # And the table is exhaustive (a CanonicalAction can't be missing a mapping).
    assert set(ACTION_DOWNMAP) == set(CanonicalAction)


# --------------------------------------------------------------------------- #
# Four outcome states                                                          #
# --------------------------------------------------------------------------- #

def test_state_confident():
    m = _mapping(transaction_date=0, action=1, ticker=2, quantity=3, price=4, net_amount=5)
    cr = _classify(m, ["2024-01-05", "Buy", "AAPL", "10", "180.00", "-1800.00"])
    assert cr.state is RowState.CONFIDENT
    assert cr.canonical_action is CanonicalAction.BUY
    assert cr.emitted_action == "BUY"
    assert cr.action_inferred is False
    assert cr.missing_fields == []
    assert cr.confidence >= 0.8


def test_state_with_assumptions_when_action_inferred():
    # No action column — IB-style signed quantity, action inferred from shape.
    m = _mapping(transaction_date=0, ticker=1, quantity=2, price=3, net_amount=4)
    cr = _classify(m, ["2024-01-15", "AAPL", "-10", "185.50", "-1855.00"])
    assert cr.state is RowState.WITH_ASSUMPTIONS
    assert cr.canonical_action is CanonicalAction.BUY
    assert cr.action_inferred is True
    assert any("inferred" in d for d in cr.diagnostics)


def test_state_partial_blocks_named_calc():
    # Buy with a security + date but only quantity → n_of(2 of qty/price/net) fails.
    m = _mapping(transaction_date=0, action=1, ticker=2, quantity=3)
    cr = _classify(m, ["2024-01-05", "Buy", "AAPL", "10"])
    assert cr.state is RowState.PARTIAL
    assert any("quantity" in g for g in cr.missing_fields)
    assert any("ACB" in d for d in cr.diagnostics)


def test_state_unmapped_is_kept_not_dropped():
    # Only a reference id — no date, no value: nothing to anchor on.
    m = _mapping(reference_id=0)
    cr = _classify(m, ["REF-12345"])
    assert cr.state is RowState.UNMAPPED
    assert cr.dropped is False
    assert cr is not None
    assert cr.confidence <= 0.2


# --------------------------------------------------------------------------- #
# Debit / credit → signed net_amount                                          #
# --------------------------------------------------------------------------- #

def test_debit_credit_merge_inflow():
    m = _mapping(transaction_date=0, action=1, debit=2, credit=3)
    nr = normalize_row(["2024-02-05", "Deposit", "", "5000.00"], m)
    assert nr.values[F.NET_AMOUNT] == 5000.00
    assert F.NET_AMOUNT in nr.derived
    assert any("credit" in d and "debit" in d for d in nr.derivations)


def test_debit_credit_merge_outflow_is_negative():
    m = _mapping(transaction_date=0, action=1, debit=2, credit=3)
    nr = normalize_row(["2024-03-01", "Fee", "9.95", ""], m)
    assert nr.values[F.NET_AMOUNT] == -9.95


# --------------------------------------------------------------------------- #
# Derivation: net_amount from quantity × price                                #
# --------------------------------------------------------------------------- #

def test_net_derived_from_quantity_times_price():
    m = _mapping(transaction_date=0, action=1, ticker=2, quantity=3, price=4)
    nr = normalize_row(["2024-01-05", "Buy", "AAPL", "10", "180.00"], m)
    assert nr.values[F.NET_AMOUNT] == -1800.00  # buy → outflow, negative
    assert F.NET_AMOUNT in nr.derived
    assert any("quantity × price" in d for d in nr.derivations)


def test_present_net_is_not_overwritten_by_derivation():
    m = _mapping(transaction_date=0, action=1, ticker=2, quantity=3, price=4, net_amount=5)
    nr = normalize_row(["2024-01-05", "Buy", "AAPL", "10", "180.00", "-1795.05"], m)
    assert nr.values[F.NET_AMOUNT] == -1795.05
    assert F.NET_AMOUNT in nr.present
    assert F.NET_AMOUNT not in nr.derived


# --------------------------------------------------------------------------- #
# Action inferred from sign when the action column is absent                  #
# --------------------------------------------------------------------------- #

def test_action_inferred_sell_from_positive_net():
    m = _mapping(transaction_date=0, ticker=1, quantity=2, net_amount=3)
    nr = normalize_row(["2024-06-20", "AAPL", "8", "1714.85"], m)
    action, conf, inferred = infer_action(nr)
    assert action is CanonicalAction.SELL
    assert inferred is True
    cr = classify_row(nr, m)
    assert cr.emitted_action == "SELL"


def test_action_inferred_buy_from_negative_net():
    m = _mapping(transaction_date=0, ticker=1, quantity=2, net_amount=3)
    nr = normalize_row(["2024-01-15", "AAPL", "10", "-1855.00"], m)
    action, _conf, inferred = infer_action(nr)
    assert action is CanonicalAction.BUY
    assert inferred is True


# --------------------------------------------------------------------------- #
# Sign inference from action keyword (missing minus)                          #
# --------------------------------------------------------------------------- #

def test_missing_minus_inferred_for_buy():
    # Source gives an unsigned positive amount for a BUY → inferred negative.
    m = _mapping(transaction_date=0, action=1, ticker=2, quantity=3, net_amount=4)
    nr = normalize_row(["2024-01-05", "Buy", "AAPL", "10", "1800.00"], m)
    assert nr.values[F.NET_AMOUNT] == -1800.00
    assert any("sign set negative" in a for a in nr.assumptions)


# --------------------------------------------------------------------------- #
# Quantity sign convention                                                    #
# --------------------------------------------------------------------------- #

def test_signed_quantity_stored_as_magnitude():
    m = _mapping(transaction_date=0, ticker=1, quantity=2, net_amount=3)
    nr = normalize_row(["2024-01-15", "AAPL", "-10", "-1855.00"], m)
    assert nr.values[F.QUANTITY] == 10.0
    assert nr.quantity_sign == -1


# --------------------------------------------------------------------------- #
# Settlement → transaction date fallback                                      #
# --------------------------------------------------------------------------- #

def test_settlement_date_fallback():
    m = _mapping(settlement_date=0, action=1, net_amount=2)
    nr = normalize_row(["2024-02-05", "Deposit", "5000.00"], m)
    assert nr.values[F.TRANSACTION_DATE] == date(2024, 2, 5)
    assert F.TRANSACTION_DATE in nr.derived


# --------------------------------------------------------------------------- #
# classify_table convenience                                                  #
# --------------------------------------------------------------------------- #

def test_classify_table_keeps_every_row():
    m = _mapping(transaction_date=0, action=1, ticker=2, quantity=3, price=4, net_amount=5)
    rows = [
        ["2024-01-05", "Buy", "AAPL", "10", "180.00", "-1800.00"],
        ["2024-02-10", "Sell", "MSFT", "5", "390.00", "1948.00"],
        ["garbage", "", "", "", "", ""],
    ]
    out = classify_table(rows, m)
    assert len(out) == 3  # nothing dropped, including the garbage row
    assert all(not cr.dropped for cr in out)
