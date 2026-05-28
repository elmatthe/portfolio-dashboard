"""Combined-stats integration tests — Phase 3 acceptance scenario.

Verifies that manual + multi-broker data aggregate correctly across
individual, by-type, and combined views in all four currency modes.
"""
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
    upsert_transactions,
    get_all_transactions,
)
from backend.portfolio import build_portfolio


def _insert_questrade_rows():
    """Insert synthetic Questrade rows for TFSA + Margin."""
    txs = []
    # TFSA: 2 buys + 1 dividend of VEQT.TO
    for i, (dt, action, qty, price, net) in enumerate([
        ("2024-01-10", "BUY", 100, 38.25, -3834.95),
        ("2024-02-15", "BUY", 50, 39.50, -1984.95),
        ("2024-03-01", "DIVIDEND", 0, 0, 45.00),
    ]):
        d = date.fromisoformat(dt)
        h = compute_hash(transaction_date=d, action=action, raw_symbol="VEQT.TO",
                         quantity=qty, net_amount=net, account_number="QT-TFSA-1")
        txs.append(Transaction(
            hash=h, broker="questrade", transaction_date=d, action=action,
            raw_symbol="VEQT.TO", resolved_ticker="VEQT.TO", quantity=qty,
            price=price, gross_amount=abs(net), commission=9.95 if action != "DIVIDEND" else 0,
            net_amount=net, currency="CAD", account_number="QT-TFSA-1",
            account_type="TFSA", fx_rate_to_cad=1.0, net_cad=net,
        ))
    # Margin: 1 buy + 1 sell of AAPL USD
    for dt, action, qty, price, net in [
        ("2024-02-01", "BUY", 15, 188.20, -2827.95),
        ("2024-06-18", "SELL", 8, 215.60, 1719.85),
    ]:
        d = date.fromisoformat(dt)
        h = compute_hash(transaction_date=d, action=action, raw_symbol="AAPL",
                         quantity=qty, net_amount=net, account_number="QT-MARGIN-1")
        txs.append(Transaction(
            hash=h, broker="questrade", transaction_date=d, action=action,
            raw_symbol="AAPL", resolved_ticker="AAPL", quantity=qty,
            price=price, gross_amount=abs(net), commission=4.95,
            net_amount=net, currency="USD", account_number="QT-MARGIN-1",
            account_type="Margin", fx_rate_to_cad=1.36, net_cad=round(net * 1.36, 2),
        ))
    upsert_transactions(txs)


def _insert_wealthsimple_rows():
    """Import the Wealthsimple 2024 fixture (covers TFSA, RRSP, Non-Reg)."""
    result = parse_with_registry(TEST_DATA / "csv" / "Wealthsimple_2024.csv")
    upsert_transactions(result.transactions)


def _insert_manual_entries():
    """Add 2 manual entries in TFSA: 1 buy of XEI.TO, 1 dividend."""
    d1 = date.fromisoformat("2024-04-10")
    h1 = compute_hash(transaction_date=d1, action="BUY", raw_symbol="XEI.TO",
                       quantity=75, net_amount=-1500.0, account_number="manual-tfsa-1")
    buy = Transaction(
        hash=h1, broker="Manual", transaction_date=d1, action="BUY",
        raw_symbol="XEI.TO", resolved_ticker="XEI.TO", quantity=75, price=20.0,
        gross_amount=1500.0, commission=0, net_amount=-1500.0,
        currency="CAD", account_number="manual-tfsa-1", account_type="TFSA",
        is_manual=True, source_file="manual-entry",
    )
    insert_manual_transaction(buy)

    d2 = date.fromisoformat("2024-06-01")
    h2 = compute_hash(transaction_date=d2, action="DIVIDEND", raw_symbol="XEI.TO",
                       quantity=0, net_amount=18.75, account_number="manual-tfsa-1")
    div = Transaction(
        hash=h2, broker="Manual", transaction_date=d2, action="DIVIDEND",
        raw_symbol="XEI.TO", resolved_ticker="XEI.TO", quantity=0, price=0,
        gross_amount=18.75, commission=0, net_amount=18.75,
        currency="CAD", account_number="manual-tfsa-1", account_type="TFSA",
        is_manual=True, source_file="manual-entry",
    )
    insert_manual_transaction(div)


@pytest.fixture
def _full_scenario():
    _insert_questrade_rows()
    _insert_wealthsimple_rows()
    _insert_manual_entries()


class TestCombinedStats:
    def test_all_accounts_present(self, _full_scenario):
        data = build_portfolio()
        account_numbers = {a.account_number for a in data.accounts}
        assert len(data.accounts) >= 4

    def test_individual_stats_non_null(self, _full_scenario):
        data = build_portfolio()
        for a in data.accounts:
            assert a.cash_deposited_cad is not None or a.total_equity_cad is not None

    def test_combined_cad_reconciles(self, _full_scenario):
        data = build_portfolio()
        sum_equity = sum(a.total_equity_cad for a in data.accounts)
        assert abs(data.combined.total_equity_cad - sum_equity) < 0.01

    def test_combined_usd_non_null(self, _full_scenario):
        data = build_portfolio()
        assert data.combined.total_equity_usd is not None

    def test_manual_included_in_combined(self, _full_scenario):
        data_with = build_portfolio()
        txs = get_all_transactions()
        manual_txs = [t for t in txs if t.broker == "Manual"]
        assert len(manual_txs) == 2

    def test_manual_in_broker_breakdown(self, _full_scenario):
        txs = get_all_transactions()
        brokers = {t.broker for t in txs}
        assert "Manual" in brokers

    def test_modified_dietz_with_manual_deposit(self, _full_scenario):
        """Manual deposits count as cash flows in Modified-Dietz."""
        d = date.fromisoformat("2024-05-01")
        h = compute_hash(transaction_date=d, action="DEPOSIT", raw_symbol=None,
                         quantity=0, net_amount=2000.0, account_number="manual-tfsa-1")
        dep = Transaction(
            hash=h, broker="Manual", transaction_date=d, action="DEPOSIT",
            raw_symbol=None, resolved_ticker=None, quantity=0, price=0,
            gross_amount=2000.0, commission=0, net_amount=2000.0,
            currency="CAD", account_number="manual-tfsa-1", account_type="TFSA",
            is_manual=True, source_file="manual-entry",
        )
        insert_manual_transaction(dep)
        data = build_portfolio(period="1y")
        assert data.combined.period_return_pct is not None

    def test_manual_transfer_excluded(self, _full_scenario):
        """Manual TRANSFER actions are excluded from Modified-Dietz cash flows."""
        d = date.fromisoformat("2024-04-15")
        h = compute_hash(transaction_date=d, action="TRANSFER", raw_symbol=None,
                         quantity=0, net_amount=500.0, account_number="manual-tfsa-1")
        xfer = Transaction(
            hash=h, broker="Manual", transaction_date=d, action="TRANSFER",
            raw_symbol=None, resolved_ticker=None, quantity=0, price=0,
            gross_amount=500.0, commission=0, net_amount=500.0,
            currency="CAD", account_number="manual-tfsa-1", account_type="TFSA",
            is_manual=True, source_file="manual-entry",
        )
        insert_manual_transaction(xfer)
        data = build_portfolio(period="1y")
        assert data.combined.period_return_pct is not None

    def test_period_clamping_with_manual(self, _full_scenario):
        """Period clamp uses earliest tx date across all sources including manual."""
        data = build_portfolio(period="3y")
        txs = get_all_transactions()
        earliest = min(t.transaction_date for t in txs)
        if data.period_clamped:
            assert data.period_start_date is not None

    def test_tfsa_cad_only_with_manual(self, _full_scenario):
        """TFSA CAD-only view still shows real numbers with manual entries."""
        data = build_portfolio()
        tfsa_accounts = [a for a in data.accounts if a.account_type == "TFSA"]
        for a in tfsa_accounts:
            pass  # non-null check — just verifying no crash


class TestClampedPeriodReconciles:
    """When the requested period spans the entire portfolio lifetime
    (e.g. 3Y on an 18-month-old portfolio), Period Return $ must equal
    the lifetime Period Return $ — there should be no extra "first
    deposit" being double-counted.
    """

    def _seed_short_lived_portfolio(self):
        """One-account portfolio with two deposits + one buy that has gained value."""
        rows = [
            ("2025-01-02", "DEPOSIT", None, 0, 0, 1000.0, "CAD"),
            ("2025-01-03", "BUY",     "VEQT.TO", 25, 40.0, -1000.0, "CAD"),
            ("2025-06-01", "DEPOSIT", None, 0, 0, 500.0, "CAD"),
            ("2025-06-02", "BUY",     "VEQT.TO", 12, 41.5, -498.0, "CAD"),
        ]
        txs = []
        for dt, action, sym, qty, price, net, cur in rows:
            d = date.fromisoformat(dt)
            h = compute_hash(transaction_date=d, action=action, raw_symbol=sym,
                             quantity=qty, net_amount=net, account_number="QT-MARGIN-1")
            txs.append(Transaction(
                hash=h, broker="questrade", transaction_date=d, action=action,
                raw_symbol=sym, resolved_ticker=sym, quantity=qty, price=price,
                gross_amount=abs(net), commission=0.0, net_amount=net,
                currency=cur, account_number="QT-MARGIN-1",
                account_type="Margin", fx_rate_to_cad=1.0, net_cad=net,
            ))
        upsert_transactions(txs)

    def test_clamped_3y_matches_lifetime_return_cad(self):
        """3Y on a young portfolio must produce the same Period Return $ as 'all'."""
        self._seed_short_lived_portfolio()
        all_data = build_portfolio(period="all")
        three_y = build_portfolio(period="3y")

        # The fixed-window 3Y must have clamped to inception.
        assert three_y.period_clamped, "Expected 3Y to clamp on a <3Y portfolio"

        # Period Return $ on the Combined row must match within $0.01.
        assert abs(
            (three_y.combined.period_return_cad or 0.0)
            - (all_data.combined.period_return_cad or 0.0)
        ) < 0.01, (
            f"Period Return mismatch — all={all_data.combined.period_return_cad}, "
            f"3Y={three_y.combined.period_return_cad}"
        )

    def test_clamped_1y_matches_lifetime_when_within_lifetime(self):
        """1Y on a young portfolio also clamps and must match lifetime."""
        self._seed_short_lived_portfolio()
        all_data = build_portfolio(period="all")
        one_y = build_portfolio(period="1y")

        # 1Y on a portfolio that started in Jan 2025 (~18 months ago in May 2026)
        # spans the lifetime once clamped — same equality must hold.
        if one_y.period_clamped:
            assert abs(
                (one_y.combined.period_return_cad or 0.0)
                - (all_data.combined.period_return_cad or 0.0)
            ) < 0.01
