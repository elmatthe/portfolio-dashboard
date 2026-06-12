"""BUG-002 regression — CRA-correct CAD capital-gain math.

The old engine kept ACB only in the security's native currency and computed
`total_gain_cad = native_gain x sell-date FX`, which erases the FX leg of the
gain entirely: a USD position bought at FX 1.20 and sold at the same USD price
at FX 1.40 reported $0 CAD gain instead of the real CAD gain.

CRA-correct math (now implemented as a parallel CAD ledger):
    CAD ACB      = sum over buys of (qty x price + commission) x BUY-date FX
    CAD proceeds = (qty x price - commission) x SELL-date FX
    CAD gain     = CAD proceeds - CAD ACB of the shares sold

Invariants under test:
  - flat native price + FX up   -> positive CAD gain (was 0 before the fix)
  - flat native price + FX down -> CAD loss          (was 0 before the fix)
  - same FX at buy and sell     -> CAD gain == native gain x FX (reconciles)
  - CAD positions               -> total_gain_cad == total_gain exactly
  - native `total_gain` and native ACB are byte-identical to before the fix
  - superficial-loss denial applies to the CAD leg proportionally
  - the aggregated report totals and /api/capital-gains carry the new figures
"""
from __future__ import annotations

from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from backend import market_data
from backend.acb import compute
from backend.main import app
from backend.models import Transaction
from backend.parser import compute_hash
from backend.store import upsert_transactions


def _make_tx(*, tx_date: str, action: str, ticker: str = "ZZUS",
             qty: float = 0.0, price: float = 0.0, commission: float = 0.0,
             currency: str = "USD", fx: float | None = None,
             account_type: str = "Margin", account_number: str = "ACC-1") -> Transaction:
    """Build a transaction whose stored fx_rate_to_cad drives the CAD ledger.

    `fx=None` leaves the stored rate empty so the engine must fall back to the
    `fx_rate_for_date` callable.
    """
    d = date.fromisoformat(tx_date)
    # net: BUY = -(qty*price) - commission ; SELL = qty*price - commission
    net = (-(abs(qty) * price) - commission) if action == "BUY" else (abs(qty) * price - commission)
    h = compute_hash(transaction_date=d, action=action, raw_symbol=ticker,
                     quantity=qty, net_amount=net, account_number=account_number)
    return Transaction(
        hash=h, broker="questrade", transaction_date=d, action=action,
        raw_symbol=ticker, resolved_ticker=ticker, quantity=qty, price=price,
        commission=commission, net_amount=net, currency=currency,
        account_number=account_number, account_type=account_type,
        fx_rate_to_cad=fx, net_cad=(round(net * fx, 2) if fx is not None else None),
    )


def _fx_stub(d, c):
    """Permissive default for the totals pass (incl. the legacy today-FX
    lookup that BUG-007 will remove)."""
    return 1.0


# --------------------------------------------------------------------------- #
# Core CRA math — flat price, FX moves
# --------------------------------------------------------------------------- #

class TestFxLegOfGain:
    def test_flat_usd_price_fx_up_positive_cad_gain(self):
        """Audit repro: buy 100 @ USD 10 at FX 1.20, sell 100 @ USD 10 at FX 1.40.
        Native gain 0; CAD gain must be (1000 x 1.40) - (1000 x 1.20) = +200."""
        txs = [
            _make_tx(tx_date="2024-01-01", action="BUY", qty=100, price=10.0, fx=1.20),
            _make_tx(tx_date="2024-06-01", action="SELL", qty=100, price=10.0, fx=1.40),
        ]
        _, report = compute(txs, fx_rate_for_date=_fx_stub)
        g = report.realized_gains[0]
        assert g.total_gain == pytest.approx(0.0, abs=0.01)
        assert g.total_gain_cad == pytest.approx(200.0, abs=0.01)
        assert report.total_taxable_gain_cad == pytest.approx(200.0, abs=0.01)

    def test_flat_usd_price_fx_down_cad_loss(self):
        txs = [
            _make_tx(tx_date="2024-01-01", action="BUY", qty=100, price=10.0, fx=1.40),
            _make_tx(tx_date="2024-06-01", action="SELL", qty=100, price=10.0, fx=1.20),
        ]
        _, report = compute(txs, fx_rate_for_date=_fx_stub)
        g = report.realized_gains[0]
        assert g.total_gain == pytest.approx(0.0, abs=0.01)
        assert g.total_gain_cad == pytest.approx(-200.0, abs=0.01)
        assert report.total_taxable_gain_cad == pytest.approx(-200.0, abs=0.01)

    def test_same_fx_reconciles_native_and_cad(self):
        """When FX is identical at buy and sell, CAD gain == native gain x FX."""
        fx = 1.36
        txs = [
            _make_tx(tx_date="2024-01-01", action="BUY", qty=100, price=40.0,
                     commission=10.0, fx=fx),
            _make_tx(tx_date="2024-06-01", action="SELL", qty=50, price=45.0,
                     commission=10.0, fx=fx),
        ]
        _, report = compute(txs, fx_rate_for_date=_fx_stub)
        g = report.realized_gains[0]
        acb_ps = (100 * 40.0 + 10.0) / 100
        expected_native = (45.0 - acb_ps) * 50 - 10.0
        assert g.total_gain == pytest.approx(expected_native, abs=0.01)
        assert g.total_gain_cad == pytest.approx(expected_native * fx, abs=0.01)

    def test_eur_fx_move(self):
        txs = [
            _make_tx(tx_date="2024-02-01", action="BUY", ticker="ZZEU", qty=10,
                     price=100.0, currency="EUR", fx=1.45),
            _make_tx(tx_date="2024-08-01", action="SELL", ticker="ZZEU", qty=10,
                     price=100.0, currency="EUR", fx=1.50),
        ]
        _, report = compute(txs, fx_rate_for_date=_fx_stub)
        g = report.realized_gains[0]
        assert g.total_gain == pytest.approx(0.0, abs=0.01)
        assert g.total_gain_cad == pytest.approx(1000 * 1.50 - 1000 * 1.45, abs=0.01)

    def test_jpy_large_nominal_fx_move(self):
        """1,000,000 JPY nominal: 10,000 shares @ 100 JPY, FX 0.0090 -> 0.0095."""
        txs = [
            _make_tx(tx_date="2024-02-01", action="BUY", ticker="ZZJP", qty=10_000,
                     price=100.0, currency="JPY", fx=0.0090),
            _make_tx(tx_date="2024-08-01", action="SELL", ticker="ZZJP", qty=10_000,
                     price=100.0, currency="JPY", fx=0.0095),
        ]
        _, report = compute(txs, fx_rate_for_date=_fx_stub)
        g = report.realized_gains[0]
        assert g.total_gain == pytest.approx(0.0, abs=0.01)
        assert g.total_gain_cad == pytest.approx(1_000_000 * 0.0095 - 1_000_000 * 0.0090, abs=0.01)

    def test_commission_at_both_ends(self):
        """Buy commission folds into CAD ACB at buy FX; sell commission reduces
        CAD proceeds at sell FX."""
        txs = [
            _make_tx(tx_date="2024-01-01", action="BUY", qty=100, price=10.0,
                     commission=5.0, fx=1.20),
            _make_tx(tx_date="2024-06-01", action="SELL", qty=100, price=10.0,
                     commission=5.0, fx=1.40),
        ]
        _, report = compute(txs, fx_rate_for_date=_fx_stub)
        g = report.realized_gains[0]
        expected_cad = (100 * 10.0 * 1.40 - 5.0 * 1.40) - (100 * 10.0 + 5.0) * 1.20
        assert g.total_gain_cad == pytest.approx(expected_cad, abs=0.01)
        # native unchanged: (10 - 10.05) * 100 - 5
        assert g.total_gain == pytest.approx(-10.0, abs=0.01)


# --------------------------------------------------------------------------- #
# CAD ACB pool mechanics
# --------------------------------------------------------------------------- #

class TestCadAcbPool:
    def test_multi_buy_weighted_cad_acb(self):
        """Two buys at different FX produce a weighted CAD ACB per share."""
        txs = [
            _make_tx(tx_date="2024-01-01", action="BUY", qty=100, price=10.0, fx=1.20),
            _make_tx(tx_date="2024-02-01", action="BUY", qty=100, price=10.0, fx=1.40),
            _make_tx(tx_date="2024-06-01", action="SELL", qty=100, price=10.0, fx=1.50),
        ]
        _, report = compute(txs, fx_rate_for_date=_fx_stub)
        g = report.realized_gains[0]
        # CAD pool = 1200 + 1400 = 2600 over 200 shares -> 13.00/share
        assert g.acb_per_share_cad == pytest.approx(13.0, abs=0.0001)
        assert g.total_gain_cad == pytest.approx((10.0 * 1.50 - 13.0) * 100, abs=0.01)
        assert g.total_gain == pytest.approx(0.0, abs=0.01)

    def test_partial_sells_keep_cad_acb_per_share(self):
        """A partial sell reduces the CAD pool proportionally; ACB/share holds."""
        txs = [
            _make_tx(tx_date="2024-01-01", action="BUY", qty=100, price=10.0, fx=1.20),
            _make_tx(tx_date="2024-03-01", action="SELL", qty=25, price=12.0, fx=1.30),
            _make_tx(tx_date="2024-06-01", action="SELL", qty=25, price=12.0, fx=1.40),
        ]
        holdings, report = compute(txs, fx_rate_for_date=_fx_stub)
        g1, g2 = sorted(report.realized_gains, key=lambda g: g.transaction_date)
        assert g1.acb_per_share_cad == pytest.approx(12.0, abs=0.0001)
        assert g2.acb_per_share_cad == pytest.approx(12.0, abs=0.0001)
        assert g1.total_gain_cad == pytest.approx((12.0 * 1.30 - 12.0) * 25, abs=0.01)
        assert g2.total_gain_cad == pytest.approx((12.0 * 1.40 - 12.0) * 25, abs=0.01)
        h = holdings[("ZZUS", "Margin")]
        assert h.total_cost_cad == pytest.approx(12.0 * 50, abs=0.01)
        assert h.acb_per_share_cad == pytest.approx(12.0, abs=0.0001)

    def test_full_sell_zeroes_cad_pool(self):
        txs = [
            _make_tx(tx_date="2024-01-01", action="BUY", qty=50, price=40.0, fx=1.25),
            _make_tx(tx_date="2024-06-01", action="SELL", qty=50, price=45.0, fx=1.25),
        ]
        holdings, _ = compute(txs, fx_rate_for_date=_fx_stub)
        h = holdings[("ZZUS", "Margin")]
        assert h.total_cost_cad == 0.0
        assert h.acb_per_share_cad == 0.0

    def test_callable_fallback_when_row_has_no_stored_fx(self):
        """Rows without a stored fx_rate_to_cad use the fx_rate_for_date callable
        at the row's own date — buy-date for the ACB leg, sell-date for proceeds."""
        rates = {"2024-01-01": 1.20, "2024-06-01": 1.40}

        def strict_fx(d, c):
            return rates.get(d.isoformat(), 1.0)

        txs = [
            _make_tx(tx_date="2024-01-01", action="BUY", qty=100, price=10.0, fx=None),
            _make_tx(tx_date="2024-06-01", action="SELL", qty=100, price=10.0, fx=None),
        ]
        _, report = compute(txs, fx_rate_for_date=strict_fx)
        g = report.realized_gains[0]
        assert g.total_gain_cad == pytest.approx(200.0, abs=0.01)
        assert g.fx_rate_to_cad == pytest.approx(1.40, abs=0.0001)


# --------------------------------------------------------------------------- #
# CAD-native invariance (byte-identical behaviour for CAD)
# --------------------------------------------------------------------------- #

class TestCadInvariance:
    def test_cad_gain_cad_equals_native(self):
        txs = [
            _make_tx(tx_date="2024-01-01", action="BUY", ticker="VEQT.TO", qty=100,
                     price=40.0, commission=10.0, currency="CAD", fx=1.0),
            _make_tx(tx_date="2024-06-01", action="SELL", ticker="VEQT.TO", qty=50,
                     price=45.0, commission=10.0, currency="CAD", fx=1.0),
        ]
        holdings, report = compute(txs, fx_rate_for_date=_fx_stub)
        g = report.realized_gains[0]
        assert g.total_gain_cad == pytest.approx(g.total_gain, abs=0.005)
        assert g.acb_per_share_cad == pytest.approx(g.acb_per_share, abs=0.0001)
        h = holdings[("VEQT.TO", "Margin")]
        assert h.total_cost_cad == pytest.approx(h.total_cost, abs=0.005)
        assert h.acb_per_share_cad == pytest.approx(h.acb_per_share, abs=0.0001)

    def test_native_figures_unchanged_for_usd(self):
        """The fix adds a CAD leg; native total_gain / ACB stay exactly as before."""
        txs = [
            _make_tx(tx_date="2024-01-01", action="BUY", qty=100, price=40.0,
                     commission=10.0, fx=1.20),
            _make_tx(tx_date="2024-06-01", action="SELL", qty=50, price=45.0,
                     commission=10.0, fx=1.40),
        ]
        _, report = compute(txs, fx_rate_for_date=_fx_stub)
        g = report.realized_gains[0]
        acb_ps = (100 * 40.0 + 10.0) / 100
        assert g.acb_per_share == pytest.approx(acb_ps, abs=0.0001)
        assert g.total_gain == pytest.approx((45.0 - acb_ps) * 50 - 10.0, abs=0.01)


# --------------------------------------------------------------------------- #
# Superficial loss — CAD leg of the denial
# --------------------------------------------------------------------------- #

class TestSuperficialLossCad:
    def test_denied_cad_loss_proportional(self):
        """Buy 100 @ 40, sell 50 @ 35 (loss), rebuy 30 within 30 days.
        Fraction 0.6 of the loss is denied on BOTH legs."""
        txs = [
            _make_tx(tx_date="2024-01-10", action="BUY", qty=100, price=40.0, fx=1.30),
            _make_tx(tx_date="2024-03-01", action="SELL", qty=50, price=35.0, fx=1.30),
            _make_tx(tx_date="2024-03-15", action="BUY", qty=30, price=36.0, fx=1.30),
        ]
        holdings, report = compute(txs, fx_rate_for_date=_fx_stub)
        h = holdings[("ZZUS", "Margin")]
        adj = h.superficial_loss_adjustments[0]
        # native loss -250, CAD loss -325; denied fraction 30/50 = 0.6
        assert adj.denied_loss == pytest.approx(150.0, abs=0.01)
        assert adj.denied_loss_cad == pytest.approx(195.0, abs=0.01)
        g = report.realized_gains[0]
        assert g.total_gain == pytest.approx(-100.0, abs=0.01)
        assert g.total_gain_cad == pytest.approx(-130.0, abs=0.01)
        assert report.total_superficial_loss_denied == pytest.approx(150.0, abs=0.01)
        assert report.total_superficial_loss_denied_cad == pytest.approx(195.0, abs=0.01)

    def test_native_loss_but_cad_gain_denies_zero_cad(self):
        """FX moved enough that the CAD side is a gain despite a native loss —
        there is no CAD loss to deny."""
        txs = [
            _make_tx(tx_date="2024-01-10", action="BUY", qty=100, price=40.0, fx=1.10),
            _make_tx(tx_date="2024-03-01", action="SELL", qty=100, price=39.0, fx=1.40),
            _make_tx(tx_date="2024-03-15", action="BUY", qty=100, price=39.0, fx=1.40),
        ]
        holdings, report = compute(txs, fx_rate_for_date=_fx_stub)
        h = holdings[("ZZUS", "Margin")]
        adj = h.superficial_loss_adjustments[0]
        assert adj.denied_loss > 0  # native denial unchanged
        assert adj.denied_loss_cad == pytest.approx(0.0, abs=0.005)
        g = report.realized_gains[0]
        # CAD gain: 3900 x 1.40 - 4000 x 1.10 = 5460 - 4400 = +1060 (kept intact)
        assert g.total_gain_cad == pytest.approx(1060.0, abs=0.01)


# --------------------------------------------------------------------------- #
# Aggregated level — /api/capital-gains carries the CRA-correct figures
# --------------------------------------------------------------------------- #

class TestCapitalGainsApi:
    @pytest.fixture
    def client(self, monkeypatch):
        """Offline-deterministic API client (no yfinance / BoC calls)."""

        def _fake_quote(ticker: str, max_age_minutes: int = 15):
            return market_data.QuoteResult(
                ticker=ticker, price=10.0, currency=None, stale=False,
                fetched_at=datetime(2026, 6, 1, 12, 0, 0),
            )

        def _fake_fx(pair: str = "USDCAD", max_age_minutes: int = 15):
            return (1.36, False)

        monkeypatch.setattr(market_data, "get_quote", _fake_quote)
        monkeypatch.setattr(market_data, "get_fx", _fake_fx)
        return TestClient(app)

    def test_api_reports_fx_leg_gain(self, client):
        """Stored rows (with their import-time FX) flow through build_portfolio
        into /api/capital-gains with the CRA-correct CAD totals."""
        upsert_transactions([
            _make_tx(tx_date="2024-01-05", action="BUY", qty=2, price=100.0, fx=1.20),
            _make_tx(tx_date="2024-06-05", action="SELL", qty=2, price=100.0, fx=1.40),
        ])
        r = client.get("/api/capital-gains")
        assert r.status_code == 200
        data = r.json()
        gains = data["realized_gains"]
        assert len(gains) == 1
        g = gains[0]
        # native flat -> 0; CAD: 200 x 1.40 - 200 x 1.20 = +40
        assert g["total_gain"] == pytest.approx(0.0, abs=0.01)
        assert g["total_gain_cad"] == pytest.approx(40.0, abs=0.01)
        assert g["acb_per_share_cad"] == pytest.approx(120.0, abs=0.0001)
        assert g["fx_rate_to_cad"] == pytest.approx(1.40, abs=0.0001)
        assert data["total_taxable_gain_cad"] == pytest.approx(40.0, abs=0.01)
        assert data["total_non_taxable_gain_cad"] == pytest.approx(0.0, abs=0.01)

    def test_api_year_filter_uses_new_cad_figures(self, client):
        upsert_transactions([
            _make_tx(tx_date="2023-03-03", action="BUY", qty=10, price=10.0, fx=1.25),
            _make_tx(tx_date="2024-03-03", action="SELL", qty=10, price=10.0, fx=1.45),
        ])
        r = client.get("/api/capital-gains?year=2024")
        assert r.status_code == 200
        data = r.json()
        assert len(data["realized_gains"]) == 1
        # 100 x 1.45 - 100 x 1.25 = +20
        assert data["total_taxable_gain_cad"] == pytest.approx(20.0, abs=0.01)
