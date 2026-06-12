"""BUG-004 regression — dividend report must use transaction-date CAD equivalents.

The old `dividend_report()` converted only USD — at the LIVE USD/CAD rate —
and let every other currency (GBP/EUR/JPY/AUD/CHF/HKD/SEK/NOK) fall through
1:1 as raw CAD. Monthly buckets, trailing totals, annual totals, upcoming
estimates, the period total, and yield-on-cost inputs were all wrong for the
eight non-CAD/non-USD currencies, and USD drifted with the live rate.

Now every dividend row uses its transaction-date CAD equivalent (stored
`net_cad`, then the stored row rate, then a trade-date FXService lookup for
legacy rows), and the yield-on-cost denominator is the acquisition-date-FX
CAD cost basis from the BUG-002 CAD ledger.

The autouse fixture patches the live USD/CAD rate to an absurd 2.50, so any
code path that still consults the live rate produces a loudly wrong number.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from backend import market_data
from backend.fx.rates import STATIC_RATES_TO_CAD
from backend.models import Transaction
from backend.parser import compute_hash
from backend.portfolio import dividend_report
from backend.store import upsert_transactions

ALL_CCYS = ["CAD", "USD", "GBP", "EUR", "JPY", "AUD", "CHF", "HKD", "SEK", "NOK"]

# Deliberately absurd live rate — trade-date figures must win (BUG-004).
LIVE_USD_CAD_SENTINEL = 2.50


@pytest.fixture(autouse=True)
def _patch_live_fx(monkeypatch):
    def _fake_fx(pair: str = "USDCAD", max_age_minutes: int = 15):
        return (LIVE_USD_CAD_SENTINEL, False)

    monkeypatch.setattr(market_data, "get_fx", _fake_fx)


def _seed(*, tx_date: str, action: str = "DIVIDEND", ticker: str | None = "ZZDIV",
          qty: float = 0.0, price: float = 0.0, amount: float = 100.0,
          currency: str = "CAD", fx: float | None = None,
          account_type: str = "Margin", account_number: str = "ACC-1") -> Transaction:
    """Insert one transaction. `fx=None` means 'use the static rate'; pass
    `fx=0` (falsy sentinel not used) — to create a LEGACY row with neither
    fx_rate_to_cad nor net_cad stored, pass `fx=-1`."""
    d = date.fromisoformat(tx_date)
    if fx == -1:
        rate = None
        net_cad = None
    else:
        rate = fx if fx is not None else STATIC_RATES_TO_CAD[currency]
        net_cad = round(amount * rate, 2)
    h = compute_hash(transaction_date=d, action=action, raw_symbol=ticker,
                     quantity=qty, net_amount=amount, account_number=account_number)
    tx = Transaction(
        hash=h, broker="questrade", transaction_date=d, action=action,
        raw_symbol=ticker, resolved_ticker=ticker, quantity=qty, price=price,
        gross_amount=abs(amount), commission=0, net_amount=amount,
        currency=currency, account_number=account_number, account_type=account_type,
        fx_rate_to_cad=rate, net_cad=net_cad,
    )
    upsert_transactions([tx])
    return tx


def _month_amount(report, key: str) -> float:
    for m in report.monthly:
        if m.month == key:
            return m.amount_cad
    raise AssertionError(f"month {key} not in report: {[m.month for m in report.monthly]}")


# --------------------------------------------------------------------------- #
# Monthly buckets + trailing totals — the audit's 10-currency matrix
# --------------------------------------------------------------------------- #

class TestMonthlyBuckets:
    @pytest.mark.parametrize("ccy", ALL_CCYS)
    def test_monthly_bucket_matches_net_cad(self, ccy):
        tx = _seed(tx_date="2026-01-15", amount=100.0, currency=ccy)
        rep = dividend_report(period="all")
        assert _month_amount(rep, "2026-01") == pytest.approx(tx.net_cad, abs=0.01)

    @pytest.mark.parametrize("ccy", ALL_CCYS)
    def test_trailing_12mo_matches_net_cad(self, ccy):
        tx = _seed(tx_date="2026-01-15", amount=100.0, currency=ccy)
        rep = dividend_report(period="all")
        assert rep.trailing_12mo_cad == pytest.approx(tx.net_cad, abs=0.01)

    def test_jpy_million_nominal(self):
        """1,000,000 JPY at 0.0091 must bucket as 9,100 CAD, not 1,000,000."""
        tx = _seed(tx_date="2026-02-10", amount=1_000_000.0, currency="JPY")
        rep = dividend_report(period="all")
        assert tx.net_cad == pytest.approx(9_100.0, abs=0.01)
        assert _month_amount(rep, "2026-02") == pytest.approx(9_100.0, abs=0.01)

    def test_transaction_date_rate_wins_over_live(self):
        """USD dividend stored at trade-date FX 1.30 must report 130 CAD even
        though the live rate is patched to 2.50 (pre-fix: 250)."""
        _seed(tx_date="2026-03-05", amount=100.0, currency="USD", fx=1.30)
        rep = dividend_report(period="all")
        assert _month_amount(rep, "2026-03") == pytest.approx(130.0, abs=0.01)

    def test_legacy_row_falls_back_to_trade_date_fx_service(self):
        """A row with neither net_cad nor fx_rate_to_cad uses FXService at the
        transaction date (static table offline) — not raw 1:1."""
        _seed(tx_date="2026-04-07", amount=100.0, currency="EUR", fx=-1)
        rep = dividend_report(period="all")
        assert _month_amount(rep, "2026-04") == pytest.approx(100.0 * STATIC_RATES_TO_CAD["EUR"], abs=0.01)

    def test_cad_dividends_unchanged(self):
        """CAD rows are byte-identical to before the fix (rate exactly 1.0)."""
        _seed(tx_date="2026-05-20", amount=123.45, currency="CAD")
        rep = dividend_report(period="all")
        assert _month_amount(rep, "2026-05") == pytest.approx(123.45, abs=0.001)


# --------------------------------------------------------------------------- #
# Period total
# --------------------------------------------------------------------------- #

class TestPeriodTotal:
    def test_period_total_uses_trade_date_cad(self):
        tx = _seed(tx_date="2026-02-15", amount=100.0, currency="GBP")
        rep = dividend_report(period="ytd")
        assert rep.period_total_cad == pytest.approx(tx.net_cad, abs=0.01)
        assert rep.period_total_cad == pytest.approx(172.0, abs=0.01)


# --------------------------------------------------------------------------- #
# Upcoming projections
# --------------------------------------------------------------------------- #

class TestUpcomingEstimates:
    def test_upcoming_estimate_is_cad_equivalent(self):
        """Three monthly GBP payments of 100 (net_cad 172) project an upcoming
        amount of ~172 CAD, not raw 100."""
        for iso in ("2026-02-16", "2026-03-16", "2026-04-16"):
            _seed(tx_date=iso, ticker="ZZGBP", amount=100.0, currency="GBP")
        rep = dividend_report(period="all")
        up = [u for u in rep.upcoming if u.ticker == "ZZGBP"]
        assert up, f"no upcoming projection: {rep.upcoming}"
        assert up[0].estimated_amount_cad == pytest.approx(172.0, abs=0.01)


# --------------------------------------------------------------------------- #
# Yield on cost — both legs in trade-date CAD
# --------------------------------------------------------------------------- #

class TestYieldOnCost:
    def test_usd_yoc_uses_acquisition_fx_cost(self):
        """Cost basis converts at the BUY's FX (1.25), dividends at their own
        trade-date FX (1.30) — the live 2.50 rate must appear nowhere."""
        _seed(tx_date="2025-04-01", action="BUY", ticker="ZZUS", qty=100,
              price=10.0, amount=-1000.0, currency="USD", fx=1.25)
        _seed(tx_date="2025-05-01", ticker="ZZUS", amount=50.0, currency="USD", fx=1.30)
        _seed(tx_date="2025-11-01", ticker="ZZUS", amount=50.0, currency="USD", fx=1.30)
        rep = dividend_report(period="all")
        rows = [r for r in rep.by_holding if r.ticker == "ZZUS"]
        assert rows, f"no yield row: {rep.by_holding}"
        row = rows[0]
        # CAD cost basis = 1000 x 1.25; annual dividends = 2 x 50 x 1.30
        assert row.total_cost_cad == pytest.approx(1250.0, abs=0.01)
        assert row.annual_dividends_cad == pytest.approx(130.0, abs=0.01)
        assert row.yield_on_cost_pct == pytest.approx(130.0 / 1250.0 * 100, abs=0.01)

    def test_foreign_yoc_not_raw_native(self):
        """EUR holding: pre-fix both legs were raw EUR treated as CAD."""
        _seed(tx_date="2025-04-01", action="BUY", ticker="ZZEU", qty=10,
              price=100.0, amount=-1000.0, currency="EUR")  # fx 1.48 -> 1480 CAD
        _seed(tx_date="2025-05-01", ticker="ZZEU", amount=20.0, currency="EUR")
        _seed(tx_date="2025-11-01", ticker="ZZEU", amount=20.0, currency="EUR")
        rep = dividend_report(period="all")
        row = [r for r in rep.by_holding if r.ticker == "ZZEU"][0]
        assert row.total_cost_cad == pytest.approx(1000.0 * 1.48, abs=0.01)
        assert row.annual_dividends_cad == pytest.approx(2 * 20.0 * 1.48, abs=0.01)

    def test_cad_yoc_unchanged(self):
        _seed(tx_date="2025-04-01", action="BUY", ticker="VEQT.TO", qty=100,
              price=10.0, amount=-1000.0, currency="CAD")
        _seed(tx_date="2025-05-01", ticker="VEQT.TO", amount=25.0, currency="CAD")
        _seed(tx_date="2025-11-01", ticker="VEQT.TO", amount=25.0, currency="CAD")
        rep = dividend_report(period="all")
        row = [r for r in rep.by_holding if r.ticker == "VEQT.TO"][0]
        assert row.total_cost_cad == pytest.approx(1000.0, abs=0.01)
        assert row.annual_dividends_cad == pytest.approx(50.0, abs=0.01)
        assert row.yield_on_cost_pct == pytest.approx(5.0, abs=0.01)
