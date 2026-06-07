"""BUG-001 regression — multi-currency aggregation must use net_cad / CAD-equivalent.

The row layer was always correct (net_cad = net_amount * fx). The bug lived in the
*aggregated* dashboard rollups: every non-CAD/non-USD currency fell into the CAD
bucket and was summed 1:1 as CAD. These tests assert at the aggregated level
(by-account + combined rollup, and the four currency views the frontend renders)
for all ten supported currencies, including the JPY 1,000,000 nominal case.

Invariant under test: CAD and USD outputs stay byte-identical; only the other
eight currencies change (they stop being treated as raw CAD).

View semantics (confirmed product decision, native-currency filters):
  - Combined CAD : every currency converted to CAD
  - Combined USD : every currency converted to USD (foreign via net_cad ÷ USD/CAD)
  - CAD only     : natively-CAD holdings/cash only; foreign EXCLUDED
  - USD only     : natively-USD holdings/cash only; foreign EXCLUDED
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

from backend import market_data
from backend.models import Transaction
from backend.parser import compute_hash
from backend.store import upsert_transactions
from backend.portfolio import build_portfolio
from backend.fx.rates import STATIC_RATES_TO_CAD

# Live USD/CAD used by the aggregation hot path. Set equal to the static USD rate
# so USD math is identical whether it goes through the live rate or the static
# table — keeps the CAD/USD invariant unambiguous.
USD_CAD = STATIC_RATES_TO_CAD["USD"]  # 1.36

ALL_CCYS = ["CAD", "USD", "GBP", "EUR", "JPY", "AUD", "CHF", "HKD", "SEK", "NOK"]


@pytest.fixture(autouse=True)
def _patch_market(monkeypatch):
    """Deterministic quote (current price) and live USD/CAD for build_portfolio."""

    def _fake_quote(ticker: str, max_age_minutes: int = 15):
        return market_data.QuoteResult(
            ticker=ticker, price=120.0, currency=None, stale=False,
            fetched_at=datetime(2026, 6, 1, 12, 0, 0),
        )

    def _fake_fx(pair: str = "USDCAD", max_age_minutes: int = 15):
        return (USD_CAD, False)

    monkeypatch.setattr(market_data, "get_quote", _fake_quote)
    monkeypatch.setattr(market_data, "get_fx", _fake_fx)
    # Make sure live BoC lookups never fire; static table is the source of truth.
    monkeypatch.setenv("FX_LIVE_RATES", "")


def _factor(ccy: str) -> float:
    """The CAD-equivalent multiplier for one native unit of `ccy` in the
    aggregation (USD uses the live rate, which equals its static rate here)."""
    return STATIC_RATES_TO_CAD[ccy]


def _seed_deposit(ccy: str, amount: float) -> None:
    rate = STATIC_RATES_TO_CAD[ccy]
    d = date(2024, 6, 1)
    h = compute_hash(transaction_date=d, action="DEPOSIT", raw_symbol=None,
                     quantity=0, net_amount=amount, account_number="ACC-1")
    upsert_transactions([
        Transaction(
            hash=h, broker="questrade", transaction_date=d, action="DEPOSIT",
            raw_symbol=None, resolved_ticker=None, quantity=0, price=0,
            gross_amount=amount, commission=0, net_amount=amount,
            currency=ccy, account_number="ACC-1", account_type="Margin",
            fx_rate_to_cad=rate, net_cad=round(amount * rate, 2),
        )
    ])


def _seed_holding(ccy: str) -> None:
    """deposit 10,000 native + buy 100 @ 100 native (quote later patched to 120)."""
    rate = STATIC_RATES_TO_CAD[ccy]
    rows = [
        ("DEPOSIT", None, 0, 0, 10_000.0),
        ("BUY", "ZZ" + ccy, 100, 100.0, -10_000.0),
    ]
    txs = []
    for action, sym, qty, price, net in rows:
        d = date(2024, 6, 1)
        h = compute_hash(transaction_date=d, action=action, raw_symbol=sym,
                         quantity=qty, net_amount=net, account_number="ACC-1")
        txs.append(Transaction(
            hash=h, broker="questrade", transaction_date=d, action=action,
            raw_symbol=sym, resolved_ticker=sym, quantity=qty, price=price,
            gross_amount=abs(net), commission=0, net_amount=net,
            currency=ccy, account_number="ACC-1", account_type="Margin",
            fx_rate_to_cad=rate, net_cad=round(net * rate, 2),
        ))
    upsert_transactions(txs)


def _glance(c, view: str) -> dict[str, float]:
    """Python mirror of the frontend computeGlanceMetrics — asserts against the
    exact Net Deposits / Total Equity / P&L / Simple RoR the user sees."""
    usd_to_cad = USD_CAD
    cad_to_usd = 1.0 / USD_CAD
    if view == "combined_cad":
        te = c.total_equity_cad + c.total_equity_usd * usd_to_cad + c.total_equity_other_cad
        nd = c.cash_deposited_cad + c.cash_deposited_usd * usd_to_cad + c.cash_deposited_other_cad
    elif view == "combined_usd":
        te = c.total_equity_usd + (c.total_equity_cad + c.total_equity_other_cad) * cad_to_usd
        nd = c.cash_deposited_usd + (c.cash_deposited_cad + c.cash_deposited_other_cad) * cad_to_usd
    elif view == "cad_only":
        te, nd = c.total_equity_cad, c.cash_deposited_cad
    elif view == "usd_only":
        te, nd = c.total_equity_usd, c.cash_deposited_usd
    else:  # pragma: no cover
        raise ValueError(view)
    pnl = te - nd
    ror = (pnl / nd * 100) if nd > 0 else 0.0
    return {"total_equity": te, "net_deposits": nd, "pnl": pnl, "simple_ror": ror}


# --------------------------------------------------------------------------- #
# Deposit-only matrix
# --------------------------------------------------------------------------- #

class TestDepositAggregation:
    @pytest.mark.parametrize("ccy", ALL_CCYS)
    def test_row_net_cad(self, ccy):
        _seed_deposit(ccy, 10_000.0)
        from backend.store import get_all_transactions
        tx = get_all_transactions()[0]
        assert tx.net_cad == pytest.approx(10_000.0 * _factor(ccy), abs=0.01)

    @pytest.mark.parametrize("ccy", ALL_CCYS)
    def test_combined_cad_net_deposits(self, ccy):
        """The headline bug: Combined-CAD Net Deposits must be the CAD-equivalent,
        not the raw native amount treated as CAD."""
        _seed_deposit(ccy, 10_000.0)
        data = build_portfolio()
        nd = _glance(data.combined, "combined_cad")["net_deposits"]
        assert nd == pytest.approx(10_000.0 * _factor(ccy), abs=0.01)

    @pytest.mark.parametrize("ccy", ALL_CCYS)
    def test_no_cad_bucket_pollution(self, ccy):
        """A non-CAD/non-USD deposit must NOT land in the native CAD bucket."""
        _seed_deposit(ccy, 10_000.0)
        c = build_portfolio().combined
        if ccy == "CAD":
            assert c.cash_deposited_cad == pytest.approx(10_000.0)
            assert c.cash_deposited_other_cad == 0.0
        elif ccy == "USD":
            assert c.cash_deposited_usd == pytest.approx(10_000.0)
            assert c.cash_deposited_cad == 0.0
            assert c.cash_deposited_other_cad == 0.0
        else:
            assert c.cash_deposited_cad == 0.0, "foreign deposit polluted the CAD bucket"
            assert c.cash_deposited_usd == 0.0
            assert c.cash_deposited_other_cad == pytest.approx(10_000.0 * _factor(ccy), abs=0.01)

    @pytest.mark.parametrize("ccy", ALL_CCYS)
    def test_native_filter_views_exclude_foreign(self, ccy):
        """CAD-only / USD-only are native filters: foreign is excluded entirely."""
        _seed_deposit(ccy, 10_000.0)
        c = build_portfolio().combined
        cad_only = _glance(c, "cad_only")["net_deposits"]
        usd_only = _glance(c, "usd_only")["net_deposits"]
        assert cad_only == pytest.approx(10_000.0 if ccy == "CAD" else 0.0, abs=0.01)
        assert usd_only == pytest.approx(10_000.0 if ccy == "USD" else 0.0, abs=0.01)

    def test_jpy_million_nominal(self):
        """JPY 1,000,000 must convert to ~9,100 CAD, not be summed as 1,000,000."""
        _seed_deposit("JPY", 1_000_000.0)
        data = build_portfolio()
        from backend.store import get_all_transactions
        assert get_all_transactions()[0].net_cad == pytest.approx(9_100.0, abs=0.01)
        nd = _glance(data.combined, "combined_cad")["net_deposits"]
        assert nd == pytest.approx(9_100.0, abs=0.01)
        # And it must NOT have leaked into the CAD bucket as 1,000,000.
        assert data.combined.cash_deposited_cad == 0.0


# --------------------------------------------------------------------------- #
# Holding matrix (deposit + buy + live quote)
# --------------------------------------------------------------------------- #

class TestHoldingAggregation:
    @pytest.mark.parametrize("ccy", ALL_CCYS)
    def test_combined_cad_metrics(self, ccy):
        _seed_holding(ccy)
        data = build_portfolio()
        f = _factor(ccy)
        # by-account rollup and combined rollup must agree
        assert len(data.accounts) == 1
        acct = data.accounts[0]
        g = _glance(data.combined, "combined_cad")
        g_acct = _glance(acct, "combined_cad")
        for key in ("total_equity", "net_deposits", "pnl"):
            assert g[key] == pytest.approx(g_acct[key], abs=0.01)
        assert g["total_equity"] == pytest.approx(12_000.0 * f, abs=0.01)
        assert g["net_deposits"] == pytest.approx(10_000.0 * f, abs=0.01)
        assert g["pnl"] == pytest.approx(2_000.0 * f, abs=0.01)
        assert g["simple_ror"] == pytest.approx(20.0, abs=0.01)

    @pytest.mark.parametrize("ccy", ALL_CCYS)
    def test_period_return_dollars_match_pnl(self, ccy):
        """Lifetime period return $ must equal Combined-CAD Total P&L $."""
        _seed_holding(ccy)
        data = build_portfolio(period="all")
        expected_pnl = _glance(data.combined, "combined_cad")["pnl"]
        assert data.combined.period_return_combined_cad == pytest.approx(expected_pnl, abs=0.01)


# --------------------------------------------------------------------------- #
# CAD / USD byte-identical invariant
# --------------------------------------------------------------------------- #

class TestCadUsdInvariant:
    def test_cad_holding_exact(self):
        _seed_holding("CAD")
        g = _glance(build_portfolio().combined, "combined_cad")
        assert g["total_equity"] == pytest.approx(12_000.0, abs=0.01)
        assert g["net_deposits"] == pytest.approx(10_000.0, abs=0.01)
        assert g["pnl"] == pytest.approx(2_000.0, abs=0.01)
        assert g["simple_ror"] == pytest.approx(20.0, abs=0.01)

    def test_usd_holding_exact(self):
        _seed_holding("USD")
        g = _glance(build_portfolio().combined, "combined_cad")
        assert g["total_equity"] == pytest.approx(16_320.0, abs=0.01)
        assert g["net_deposits"] == pytest.approx(13_600.0, abs=0.01)
        assert g["pnl"] == pytest.approx(2_720.0, abs=0.01)
        assert g["simple_ror"] == pytest.approx(20.0, abs=0.01)

    def test_usd_other_bucket_stays_zero(self):
        """USD must never touch the _other_cad buckets (it has its own native bucket)."""
        _seed_holding("USD")
        c = build_portfolio().combined
        assert c.total_equity_other_cad == 0.0
        assert c.cash_deposited_other_cad == 0.0
