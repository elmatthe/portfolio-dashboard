"""BUG-006 regression — multiple accounts of the same type must not collapse.

The cash side of the by-account rollup was always keyed by account_number,
but the holdings-equity attribution loop built `by_type = {account_type: bal}`
— with two Margin accounts the dict kept only the last row, so ALL Margin
holdings' market value landed on one account while the other showed cash only.

Fix separates two things that were conflated:
  - TAX ACB pooling: UNCHANGED — ledgers stay keyed (ticker, account_type),
    so CRA pooling across same-type account numbers still applies (asserted
    here: a sell from account B uses the ACB pooled with account A's buy).
  - DISPLAY ownership: AcbHolding/Holding now carry account_number (the
    account holding the largest remaining share count), and the equity loop
    attributes by account_number with account_type only as a fallback.

Single-account portfolios are asserted invariant.
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

from backend import market_data
from backend.models import Transaction
from backend.parser import compute_hash
from backend.portfolio import build_portfolio
from backend.store import upsert_transactions

USD_CAD = 1.36
QUOTE = 120.0


@pytest.fixture(autouse=True)
def _patch_market(monkeypatch):
    def _fake_quote(ticker: str, max_age_minutes: int = 15):
        return market_data.QuoteResult(
            ticker=ticker, price=QUOTE, currency=None, stale=False,
            fetched_at=datetime(2026, 6, 1, 12, 0, 0),
        )

    def _fake_fx(pair: str = "USDCAD", max_age_minutes: int = 15):
        return (USD_CAD, False)

    monkeypatch.setattr(market_data, "get_quote", _fake_quote)
    monkeypatch.setattr(market_data, "get_fx", _fake_fx)
    monkeypatch.setenv("FX_LIVE_RATES", "")


def _seed(*, account_number: str, action: str, tx_date: str = "2024-01-05",
          ticker: str | None = None, qty: float = 0.0, price: float = 0.0,
          net: float = 0.0, account_type: str = "Margin") -> None:
    d = date.fromisoformat(tx_date)
    h = compute_hash(transaction_date=d, action=action, raw_symbol=ticker,
                     quantity=qty, net_amount=net, account_number=account_number)
    upsert_transactions([
        Transaction(
            hash=h, broker="questrade", transaction_date=d, action=action,
            raw_symbol=ticker, resolved_ticker=ticker, quantity=qty, price=price,
            gross_amount=abs(net), commission=0, net_amount=net,
            currency="CAD", account_number=account_number, account_type=account_type,
            fx_rate_to_cad=1.0, net_cad=net,
        )
    ])


def _account(data, number: str):
    rows = [a for a in data.accounts if a.account_number == number]
    assert rows, f"no balances row for {number}: {[a.account_number for a in data.accounts]}"
    assert len(rows) == 1
    return rows[0]


# --------------------------------------------------------------------------- #
# Case 1 — two Margin accounts, different tickers: no collapse                 #
# --------------------------------------------------------------------------- #

class TestDifferentTickersNoCollapse:
    def _seed_two_accounts(self):
        # ACC-1: 10,000 in, all invested in ZZAA (100 sh) -> MV 12,000, cash 0
        _seed(account_number="ACC-1", action="DEPOSIT", net=10_000.0)
        _seed(account_number="ACC-1", action="BUY", ticker="ZZAA",
              qty=100, price=100.0, net=-10_000.0)
        # ACC-2: 5,000 in, 2,000 invested in ZZBB (20 sh) -> MV 2,400, cash 3,000
        _seed(account_number="ACC-2", action="DEPOSIT", net=5_000.0)
        _seed(account_number="ACC-2", action="BUY", ticker="ZZBB",
              qty=20, price=100.0, net=-2_000.0)

    def test_each_account_shows_its_own_total_equity(self):
        self._seed_two_accounts()
        data = build_portfolio()
        a1 = _account(data, "ACC-1")
        a2 = _account(data, "ACC-2")
        # Pre-fix: by_type kept one Margin row; ALL equity landed there and the
        # other row showed cash only.
        assert a1.total_equity_cad == pytest.approx(12_000.0, abs=0.01)
        assert a2.total_equity_cad == pytest.approx(3_000.0 + 2_400.0, abs=0.01)

    def test_each_account_shows_its_own_roi(self):
        self._seed_two_accounts()
        data = build_portfolio()
        # ROI = (TE - deposits) / deposits, per account.
        assert _account(data, "ACC-1").overall_roi_pct == pytest.approx(20.0, abs=0.01)
        assert _account(data, "ACC-2").overall_roi_pct == pytest.approx(8.0, abs=0.01)

    def test_combined_row_unchanged_by_attribution(self):
        """The combined rollup sums the same equity regardless of which row
        owns it — attribution must redistribute, never create or destroy."""
        self._seed_two_accounts()
        c = build_portfolio().combined
        assert c.total_equity_cad == pytest.approx(17_400.0, abs=0.01)

    def test_holdings_carry_owning_account_number(self):
        self._seed_two_accounts()
        data = build_portfolio()
        owners = {h.ticker: h.account_number for h in data.holdings}
        assert owners == {"ZZAA": "ACC-1", "ZZBB": "ACC-2"}


# --------------------------------------------------------------------------- #
# Case 2 — two Margin accounts, SAME ticker: tax pools, display stays split    #
# --------------------------------------------------------------------------- #

class TestSameTickerPoolsTaxButSplitsDisplay:
    def _seed_shared_ticker(self):
        # ACC-1: 100 sh @ 10 (cost 1,000). ACC-2: 50 sh @ 20 (cost 1,000).
        # CRA pool: 150 sh, ACB 2,000/150 = 13.3333/sh.
        _seed(account_number="ACC-1", action="DEPOSIT", net=1_000.0)
        _seed(account_number="ACC-1", action="BUY", ticker="ZZSAME",
              qty=100, price=10.0, net=-1_000.0)
        _seed(account_number="ACC-2", action="DEPOSIT", net=1_250.0, tx_date="2024-02-05")
        _seed(account_number="ACC-2", action="BUY", ticker="ZZSAME",
              qty=50, price=20.0, net=-1_000.0, tx_date="2024-02-05")
        # ACC-2 sells its 50 sh @ 25 well outside any superficial-loss window.
        _seed(account_number="ACC-2", action="SELL", ticker="ZZSAME",
              qty=50, price=25.0, net=1_250.0, tx_date="2024-06-05")

    def test_gain_uses_pooled_acb_across_account_numbers(self):
        """CRA pooling must survive the display fix: the ACC-2 sell's gain is
        (25 − 13.3333) × 50 = 583.33, NOT the per-account (25 − 20) × 50 = 250."""
        self._seed_shared_ticker()
        report = build_portfolio().capital_gains
        assert len(report.realized_gains) == 1
        g = report.realized_gains[0]
        assert g.acb_per_share == pytest.approx(2_000.0 / 150.0, abs=0.0001)
        assert g.total_gain_cad == pytest.approx(583.33, abs=0.01)
        assert report.total_taxable_gain_cad == pytest.approx(583.33, abs=0.01)

    def test_accounts_still_show_as_separate_rows(self):
        self._seed_shared_ticker()
        data = build_portfolio()
        margins = [a for a in data.accounts if a.account_type == "Margin"]
        assert sorted(a.account_number for a in margins) == ["ACC-1", "ACC-2"]

    def test_remaining_equity_attributed_to_the_account_that_holds_it(self):
        """After ACC-2 sells out, the 100 remaining shares belong to ACC-1 —
        its row carries the market value; ACC-2's row shows only its cash."""
        self._seed_shared_ticker()
        data = build_portfolio()
        # ACC-1: cash 0, 100 sh × 120 = 12,000.
        assert _account(data, "ACC-1").total_equity_cad == pytest.approx(12_000.0, abs=0.01)
        # ACC-2: 1,250 deposited − 1,000 invested = 250 cash (sell proceeds
        # don't feed cash_remaining in this model), no equity.
        assert _account(data, "ACC-2").total_equity_cad == pytest.approx(250.0, abs=0.01)


# --------------------------------------------------------------------------- #
# Case 3 — single-account portfolio: invariant                                 #
# --------------------------------------------------------------------------- #

class TestSingleAccountInvariant:
    def test_single_account_values_unchanged(self):
        _seed(account_number="ACC-1", action="DEPOSIT", net=10_000.0)
        _seed(account_number="ACC-1", action="BUY", ticker="ZZCC",
              qty=100, price=100.0, net=-10_000.0)
        data = build_portfolio()

        assert len(data.accounts) == 1
        a = data.accounts[0]
        assert a.account_number == "ACC-1"
        assert a.account_label == "Margin · ACC-1"
        assert a.total_equity_cad == pytest.approx(12_000.0, abs=0.01)
        assert a.cash_deposited_cad == pytest.approx(10_000.0, abs=0.01)
        assert a.overall_roi_pct == pytest.approx(20.0, abs=0.01)
        assert data.combined.total_equity_cad == pytest.approx(12_000.0, abs=0.01)

        h = data.holdings[0]
        assert h.ticker == "ZZCC"
        assert h.account_number == "ACC-1"
        assert h.total_shares == pytest.approx(100.0)
        assert h.acb_per_share == pytest.approx(100.0)
