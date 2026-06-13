"""BUG-005 regression — editing a manual transaction must recompute derived money.

The create path derived gross_amount / net_amount from quantity × price ∓
commission and let FXService fill fx_rate_to_cad / net_cad. The update path
just forwarded raw fields and called populate_transaction(), which only fills
when None — so editing quantity, price, commission, currency, or the
transaction date silently kept the OLD amounts, corrupting every cash/equity
aggregation built on net_amount / net_cad.

Now create and update share store.derive_manual_amounts() and the update path
force-recomputes the FX leg at the post-edit currency + transaction date.
Hash semantics: the SHA-256 hash is the row's immutable identity and is
deliberately NOT recomputed on edit (documented in
store.update_manual_transaction; asserted in TestHashSemantics).

Assertions are made at the API row level AND at the aggregated dashboard
level (Combined-CAD Total Equity), same discipline as the BUG-001 suite.
"""
from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from backend import market_data
from backend.fx.rates import STATIC_RATES_TO_CAD
from backend.main import app

USD_CAD = STATIC_RATES_TO_CAD["USD"]  # 1.36 — live rate patched to match
EUR_CAD = STATIC_RATES_TO_CAD["EUR"]  # 1.48
QUOTE = 120.0


@pytest.fixture(autouse=True)
def _patch_market(monkeypatch):
    """Deterministic quote + live USD/CAD; no network from ticker seeding."""

    def _fake_quote(ticker: str, max_age_minutes: int = 15):
        return market_data.QuoteResult(
            ticker=ticker, price=QUOTE, currency=None, stale=False,
            fetched_at=datetime(2026, 6, 1, 12, 0, 0),
        )

    def _fake_fx(pair: str = "USDCAD", max_age_minutes: int = 15):
        return (USD_CAD, False)

    def _no_resolve(raw_symbol: str, description: str | None = None):
        raise RuntimeError("offline test — ticker resolution disabled")

    monkeypatch.setattr(market_data, "get_quote", _fake_quote)
    monkeypatch.setattr(market_data, "get_fx", _fake_fx)
    monkeypatch.setattr(market_data, "resolve_ticker", _no_resolve)
    monkeypatch.setenv("FX_LIVE_RATES", "")


@pytest.fixture
def client():
    return TestClient(app)


def _post(client: TestClient, **kw) -> tuple[dict, dict]:
    """Create a manual transaction; returns (response_json, request_body)."""
    body = {
        "transaction_date": "2024-01-10",
        "action": "BUY",
        "ticker": None,
        "quantity": 0.0,
        "price": 0.0,
        "currency": "CAD",
        "commission": 0.0,
        "account_type": "Margin",
        "net_amount": None,
        **kw,
    }
    r = client.post("/api/transactions/manual", json=body)
    assert r.status_code == 201, r.text
    return r.json(), body


def _put(client: TestClient, tx_hash: str, body: dict) -> dict:
    r = client.put(f"/api/transactions/manual/{tx_hash}", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _combined_cad_total_equity(client: TestClient) -> float:
    """Combined-CAD Total Equity exactly as the dashboard glance computes it."""
    r = client.get("/api/portfolio")
    assert r.status_code == 200
    data = r.json()
    assert not data.get("error"), data
    c = data["combined"]
    return (
        c["total_equity_cad"]
        + c["total_equity_usd"] * USD_CAD
        + c["total_equity_other_cad"]
    )


# --------------------------------------------------------------------------- #
# Case 1 — BUY quantity edit: net_amount and net_cad must both move            #
# --------------------------------------------------------------------------- #

class TestBuyQuantityEdit:
    def test_put_recomputes_net_amount_and_net_cad(self, client):
        created, body = _post(client, ticker="ZZCA", quantity=50, price=40.0)
        assert created["net_amount"] == pytest.approx(-2000.0)
        assert created["net_cad"] == pytest.approx(-2000.0)

        body["quantity"] = 80
        tx = _put(client, created["hash"], body)
        assert tx["quantity"] == pytest.approx(80)
        assert tx["gross_amount"] == pytest.approx(3200.0)
        assert tx["net_amount"] == pytest.approx(-3200.0)
        # CAD invariance: rate stays exactly 1.0, net_cad tracks net_amount.
        assert tx["fx_rate_to_cad"] == pytest.approx(1.0)
        assert tx["net_cad"] == pytest.approx(-3200.0)

    def test_persisted_row_matches_response(self, client):
        created, body = _post(client, ticker="ZZCA", quantity=50, price=40.0)
        body["quantity"] = 80
        _put(client, created["hash"], body)
        rows = client.get("/api/transactions").json()
        row = next(t for t in rows if t["hash"] == created["hash"])
        assert row["gross_amount"] == pytest.approx(3200.0)
        assert row["net_amount"] == pytest.approx(-3200.0)
        assert row["net_cad"] == pytest.approx(-3200.0)

    def test_dashboard_combined_cad_total_equity_reflects_edit(self, client):
        _post(client, action="DEPOSIT", net_amount=10_000.0)
        created, body = _post(client, ticker="ZZCA", quantity=50, price=40.0)
        # cash 10,000 − 2,000 invested; holding 50 × 120
        assert _combined_cad_total_equity(client) == pytest.approx(14_000.0, abs=0.01)

        body["quantity"] = 80
        _put(client, created["hash"], body)
        # cash 10,000 − 3,200 = 6,800; holding 80 × 120 = 9,600.
        # Pre-fix the BUY's net_amount stayed −2,000 → TE wrongly 17,600.
        assert _combined_cad_total_equity(client) == pytest.approx(16_400.0, abs=0.01)


# --------------------------------------------------------------------------- #
# Case 2 — SELL commission edit: net proceeds and net_cad must move            #
# --------------------------------------------------------------------------- #

class TestSellCommissionEdit:
    def _setup_sell(self, client) -> tuple[dict, dict]:
        _post(client, action="DEPOSIT", net_amount=10_000.0, currency="USD")
        _post(client, ticker="ZZUS", quantity=100, price=10.0, currency="USD")
        return _post(client, action="SELL", ticker="ZZUS", quantity=50,
                     price=12.0, currency="USD", transaction_date="2024-03-10")

    def test_put_recomputes_proceeds_and_net_cad(self, client):
        created, body = self._setup_sell(client)
        assert created["net_amount"] == pytest.approx(600.0)
        assert created["net_cad"] == pytest.approx(816.0)  # 600 × 1.36

        body["commission"] = 9.99
        tx = _put(client, created["hash"], body)
        assert tx["net_amount"] == pytest.approx(590.01)   # 50 × 12 − 9.99
        assert tx["fx_rate_to_cad"] == pytest.approx(USD_CAD)
        assert tx["net_cad"] == pytest.approx(802.41)      # round(590.01 × 1.36)

    def test_dashboard_combined_cad_total_equity_reflects_edit(self, client):
        created, body = self._setup_sell(client)
        body["commission"] = 9.99
        _put(client, created["hash"], body)
        # USD leg: 10,000 deposited − 1,000 invested − 9.99 commission fee
        # (sell proceeds don't feed cash_remaining in this model);
        # holding 50 × 120 USD. Combined-CAD converts at the live 1.36.
        expected_usd = (10_000.0 - 1_000.0 - 9.99) + 50 * QUOTE
        assert _combined_cad_total_equity(client) == pytest.approx(
            expected_usd * USD_CAD, abs=0.01
        )


# --------------------------------------------------------------------------- #
# Case 3 — currency + date edit: FX rate must be recalculated, not stale       #
# --------------------------------------------------------------------------- #

class TestCurrencyAndDateEdit:
    def test_put_recomputes_fx_rate_and_net_cad(self, client):
        created, body = _post(client, ticker="ZZEU", quantity=10, price=100.0)
        assert created["fx_rate_to_cad"] == pytest.approx(1.0)
        assert created["net_cad"] == pytest.approx(-1000.0)

        body["currency"] = "EUR"
        body["transaction_date"] = "2024-02-10"
        tx = _put(client, created["hash"], body)
        assert tx["currency"] == "EUR"
        assert tx["transaction_date"] == "2024-02-10"
        assert tx["fx_rate_to_cad"] == pytest.approx(EUR_CAD)  # stale would be 1.0
        assert tx["net_amount"] == pytest.approx(-1000.0)      # native unchanged
        assert tx["net_cad"] == pytest.approx(-1480.0)

    def test_dashboard_combined_cad_total_equity_reflects_edit(self, client):
        _post(client, action="DEPOSIT", net_amount=10_000.0)
        created, body = _post(client, ticker="ZZEU", quantity=10, price=100.0)
        body["currency"] = "EUR"
        body["transaction_date"] = "2024-02-10"
        _put(client, created["hash"], body)
        # CAD leg: the 10,000 deposit. EUR leg (CAD-equivalent bucket):
        # invested 1,480 (net_cad), holding 10 × 120 EUR × 1.48 = 1,776
        # → other_cad equity = 1,776 − 1,480 = 296.
        # Pre-fix the stale net_cad (−1,000) made the EUR leg 776.
        assert _combined_cad_total_equity(client) == pytest.approx(10_296.0, abs=0.01)


# --------------------------------------------------------------------------- #
# Cash-action edits and hash semantics                                         #
# --------------------------------------------------------------------------- #

class TestCashActionEdit:
    def test_deposit_amount_edit_recomputes_net_cad(self, client):
        """net_amount is the raw input for cash actions; pre-fix the PUT
        endpoint never even forwarded it."""
        created, body = _post(client, action="DEPOSIT", net_amount=5_000.0, currency="EUR")
        assert created["net_cad"] == pytest.approx(7_400.0)

        body["net_amount"] = 6_000.0
        tx = _put(client, created["hash"], body)
        assert tx["net_amount"] == pytest.approx(6_000.0)
        assert tx["gross_amount"] == pytest.approx(6_000.0)
        assert tx["net_cad"] == pytest.approx(8_880.0)  # 6,000 × 1.48


class TestHashSemantics:
    def test_hash_is_immutable_identity_on_edit(self, client):
        """Editing intrinsic hash inputs (quantity → net_amount) must keep the
        original hash and never create a second row."""
        created, body = _post(client, ticker="ZZCA", quantity=50, price=40.0)
        body["quantity"] = 80
        tx = _put(client, created["hash"], body)
        assert tx["hash"] == created["hash"]

        rows = client.get("/api/transactions").json()
        assert [t["hash"] for t in rows].count(created["hash"]) == 1
        assert len(rows) == 1
