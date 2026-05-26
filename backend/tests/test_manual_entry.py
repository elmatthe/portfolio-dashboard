"""Tests for manual transaction entry CRUD — store layer."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEST_DATA = PROJECT_ROOT / "test_data"

from backend.models import Transaction
from backend.parser import compute_hash
from backend.parsers.registry import parse_with_registry
from backend.store import (
    insert_manual_transaction,
    update_manual_transaction,
    delete_manual_transaction,
    get_transaction_by_hash,
    get_held_quantity,
    upsert_transactions,
    get_all_transactions,
)


def _make_manual_tx(
    *,
    tx_date: str = "2024-03-10",
    action: str = "BUY",
    ticker: str = "VEQT.TO",
    qty: float = 50.0,
    price: float = 39.25,
    commission: float = 0.0,
    currency: str = "CAD",
    account_type: str = "TFSA",
    account_number: str = "manual-tfsa-1",
) -> Transaction:
    d = date.fromisoformat(tx_date)
    net = -(qty * price + commission) if action == "BUY" else (qty * price - commission)
    gross = qty * price if action in ("BUY", "SELL") else abs(net)
    h = compute_hash(
        transaction_date=d,
        action=action,
        raw_symbol=ticker,
        quantity=qty,
        net_amount=net,
        account_number=account_number,
    )
    return Transaction(
        hash=h,
        broker="Manual",
        transaction_date=d,
        action=action,
        raw_symbol=ticker,
        resolved_ticker=ticker,
        quantity=qty,
        price=price,
        gross_amount=gross,
        commission=commission,
        net_amount=net,
        currency=currency,
        account_number=account_number,
        account_type=account_type,
        is_manual=True,
        source_file="manual-entry",
    )


class TestInsertManual:
    def test_insert_buy_stored_correctly(self):
        tx = _make_manual_tx()
        result = insert_manual_transaction(tx)
        assert result.broker == "Manual"
        assert result.is_manual is True
        assert result.fx_rate_to_cad is not None
        assert result.net_cad is not None

    def test_insert_buy_fx_at_trade_date(self):
        tx = _make_manual_tx(currency="USD", tx_date="2024-01-15")
        result = insert_manual_transaction(tx)
        assert result.fx_rate_to_cad is not None
        assert result.fx_rate_to_cad != 0.0

    def test_insert_duplicate_raises(self):
        tx = _make_manual_tx()
        insert_manual_transaction(tx)
        tx2 = _make_manual_tx()
        with pytest.raises(ValueError, match="Duplicate"):
            insert_manual_transaction(tx2)

    def test_insert_oversell_raises(self):
        tx = _make_manual_tx(action="SELL", qty=100, price=40.0)
        with pytest.raises(ValueError, match="exceeds held position"):
            insert_manual_transaction(tx)

    def test_insert_after_buy_allows_sell(self):
        buy = _make_manual_tx(action="BUY", qty=100, price=38.0, tx_date="2024-01-10")
        insert_manual_transaction(buy)
        sell = _make_manual_tx(action="SELL", qty=50, price=40.0, tx_date="2024-03-10")
        result = insert_manual_transaction(sell)
        assert result.action == "SELL"


class TestUpdateManual:
    def test_update_manual_entry(self):
        tx = _make_manual_tx()
        insert_manual_transaction(tx)
        updated = update_manual_transaction(tx.hash, {"quantity": 75.0})
        assert updated.quantity == 75.0

    def test_update_imported_raises(self):
        ws_file = TEST_DATA / "csv" / "Wealthsimple_2024.csv"
        result = parse_with_registry(ws_file)
        upsert_transactions(result.transactions)
        imported_hash = result.transactions[0].hash
        with pytest.raises(ValueError, match="Cannot edit imported"):
            update_manual_transaction(imported_hash, {"quantity": 999})


class TestDeleteManual:
    def test_delete_manual_entry(self):
        tx = _make_manual_tx()
        insert_manual_transaction(tx)
        assert get_transaction_by_hash(tx.hash) is not None
        delete_manual_transaction(tx.hash)
        assert get_transaction_by_hash(tx.hash) is None

    def test_delete_imported_raises(self):
        ws_file = TEST_DATA / "csv" / "Wealthsimple_2024.csv"
        result = parse_with_registry(ws_file)
        upsert_transactions(result.transactions)
        imported_hash = result.transactions[0].hash
        with pytest.raises(ValueError, match="Cannot delete imported"):
            delete_manual_transaction(imported_hash)


class TestHeldQuantity:
    def test_held_after_buy(self):
        tx = _make_manual_tx(action="BUY", qty=100, price=38.0)
        insert_manual_transaction(tx)
        assert get_held_quantity("VEQT.TO", "TFSA") == 100.0

    def test_held_after_buy_and_sell(self):
        buy = _make_manual_tx(action="BUY", qty=100, price=38.0, tx_date="2024-01-10")
        insert_manual_transaction(buy)
        sell = _make_manual_tx(action="SELL", qty=30, price=40.0, tx_date="2024-03-10")
        insert_manual_transaction(sell)
        assert abs(get_held_quantity("VEQT.TO", "TFSA") - 70.0) < 0.01


class TestManualDividendDeposit:
    def test_manual_dividend_with_ticker(self):
        tx = _make_manual_tx(action="DIVIDEND", qty=0, price=0, ticker="VEQT.TO")
        tx.net_amount = 25.50
        tx.gross_amount = 25.50
        result = insert_manual_transaction(tx)
        assert result.action == "DIVIDEND"

    def test_manual_deposit_no_ticker(self):
        d = date.fromisoformat("2024-05-01")
        h = compute_hash(
            transaction_date=d, action="DEPOSIT", raw_symbol=None,
            quantity=0, net_amount=2000.0, account_number="manual-tfsa-1",
        )
        tx = Transaction(
            hash=h, broker="Manual", transaction_date=d, action="DEPOSIT",
            raw_symbol=None, resolved_ticker=None, quantity=0, price=0,
            gross_amount=2000.0, commission=0, net_amount=2000.0,
            currency="CAD", account_number="manual-tfsa-1", account_type="TFSA",
            is_manual=True, source_file="manual-entry",
        )
        result = insert_manual_transaction(tx)
        assert result.action == "DEPOSIT"
        assert result.net_cad is not None


class TestManualEntryACBIntegration:
    def test_manual_between_imports_acb_correct(self):
        """Manual entry inserted between imported rows re-sorts chronologically."""
        from backend.acb import compute

        buy1 = _make_manual_tx(action="BUY", qty=100, price=38.00, tx_date="2024-01-05")
        insert_manual_transaction(buy1)
        buy2 = _make_manual_tx(action="BUY", qty=50, price=42.00, tx_date="2024-03-15",
                               account_number="manual-tfsa-2")
        insert_manual_transaction(buy2)
        buy_mid = _make_manual_tx(action="BUY", qty=25, price=40.00, tx_date="2024-02-10",
                                  account_number="manual-tfsa-3")
        insert_manual_transaction(buy_mid)

        txs = get_all_transactions()
        holdings, _ = compute(txs)
        h = holdings.get(("VEQT.TO", "TFSA"))
        assert h is not None
        assert h.total_shares == 175
        expected_cost = (100 * 38.00) + (25 * 40.00) + (50 * 42.00)
        assert abs(h.total_cost - expected_cost) < 0.01

    def test_manual_usd_entry_uses_static_fallback(self):
        """Manual entry in a currency with no live rate uses static fallback."""
        tx = _make_manual_tx(currency="GBP", ticker="VOD.L", tx_date="2024-06-15")
        result = insert_manual_transaction(tx)
        assert result.fx_rate_to_cad is not None
        assert result.fx_rate_to_cad > 0
        assert result.net_cad is not None

    def test_delete_unwinds_acb(self):
        """Deleting a manual sell correctly allows the shares to be held again."""
        buy = _make_manual_tx(action="BUY", qty=100, price=38.00, tx_date="2024-01-10")
        insert_manual_transaction(buy)
        sell = _make_manual_tx(action="SELL", qty=30, price=40.00, tx_date="2024-03-10")
        insert_manual_transaction(sell)
        assert abs(get_held_quantity("VEQT.TO", "TFSA") - 70.0) < 0.01
        delete_manual_transaction(sell.hash)
        assert abs(get_held_quantity("VEQT.TO", "TFSA") - 100.0) < 0.01
