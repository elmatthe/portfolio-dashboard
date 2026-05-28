"""Multi-currency FX conversion tests (GBP, EUR, JPY, AUD, CHF).

Uses the HSBC InvestDirect fixture which has holdings in 7 currencies.
Verifies that FXService static fallbacks produce non-null, non-1.0 rates
for foreign currencies, that net_cad = net_amount * fx_rate, that JPY's
small rate doesn't break totals, and that the dashboard loads cleanly
with mixed-currency holdings.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEST_DATA = PROJECT_ROOT / "test_data"

from backend.main import app
from backend.parsers.registry import parse_with_registry
from backend.store import upsert_transactions
from backend.fx.rates import FXService, STATIC_RATES_TO_CAD


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def _loaded_hsbc(client):
    """Import the HSBC fixture (CAD, USD, GBP, EUR, JPY, AUD, CHF)."""
    result = parse_with_registry(TEST_DATA / "xlsx" / "HSBC_InvestDirect_2024.xlsx")
    upsert_transactions(result.transactions)
    return result.transactions


class TestStaticFallbackRates:
    """FXService has non-trivial static rates for every currency we care about."""

    @pytest.mark.parametrize("ccy,expected_min,expected_max", [
        ("USD", 1.30, 1.45),
        ("GBP", 1.60, 1.85),
        ("EUR", 1.40, 1.60),
        ("JPY", 0.005, 0.015),
        ("AUD", 0.80, 1.00),
        ("CHF", 1.40, 1.60),
        ("HKD", 0.10, 0.25),
        ("SEK", 0.10, 0.20),
        ("NOK", 0.10, 0.20),
    ])
    def test_static_rate_in_expected_range(self, ccy, expected_min, expected_max):
        rate = STATIC_RATES_TO_CAD[ccy]
        assert expected_min <= rate <= expected_max, f"{ccy}: {rate}"

    def test_cad_is_unity(self):
        assert STATIC_RATES_TO_CAD["CAD"] == 1.0

    def test_service_returns_static_for_all_currencies(self):
        svc = FXService(live_enabled=False)
        for ccy in ["USD", "GBP", "EUR", "JPY", "AUD", "CHF"]:
            rate = svc.rate_to_cad(ccy, date(2024, 6, 1))
            assert rate is not None
            assert rate != 1.0, f"{ccy} should not be 1.0"
            assert rate > 0


class TestFXOnParsedRows:
    """Every parsed HSBC row has a non-null, currency-appropriate FX rate."""

    def test_fx_rate_non_null(self, _loaded_hsbc):
        for tx in _loaded_hsbc:
            assert tx.fx_rate_to_cad is not None, f"Missing fx_rate on {tx.transaction_date} {tx.action}"

    def test_fx_rate_not_one_for_foreign(self, _loaded_hsbc):
        for tx in _loaded_hsbc:
            if tx.currency not in ("CAD",):
                assert tx.fx_rate_to_cad != 1.0, (
                    f"{tx.currency} row on {tx.transaction_date} has fx=1.0"
                )

    def test_net_cad_close_to_net_times_fx(self, _loaded_hsbc):
        for tx in _loaded_hsbc:
            if tx.net_cad is not None and tx.fx_rate_to_cad is not None:
                expected = round(tx.net_amount * tx.fx_rate_to_cad, 2)
                pct_diff = abs(tx.net_cad - expected) / max(abs(expected), 1) * 100
                assert pct_diff < 1.0, (
                    f"net_cad mismatch on {tx.transaction_date}: "
                    f"{tx.net_cad} vs {expected} ({pct_diff:.2f}%)"
                )


class TestJPYEdgeCases:
    """JPY has a very small rate (~0.0091). Verify it doesn't break totals."""

    def test_jpy_rate_very_small(self):
        rate = STATIC_RATES_TO_CAD["JPY"]
        assert rate < 0.02

    def test_jpy_buy_produces_reasonable_cad(self, _loaded_hsbc):
        jpy_buys = [t for t in _loaded_hsbc if t.currency == "JPY" and t.action == "BUY"]
        assert len(jpy_buys) > 0
        for tx in jpy_buys:
            assert tx.net_cad is not None
            assert abs(tx.net_cad) > 100, "JPY buy should convert to a non-trivial CAD amount"
            assert abs(tx.net_cad) < 100000, "JPY buy shouldn't overflow"

    def test_jpy_dividend_converts(self, _loaded_hsbc):
        jpy_divs = [t for t in _loaded_hsbc if t.currency == "JPY" and t.action == "DIVIDEND"]
        assert len(jpy_divs) > 0
        for tx in jpy_divs:
            assert tx.net_cad is not None
            assert tx.net_cad > 0


class TestForeignSellGain:
    """A sell in a foreign currency produces a correct CAD realized gain."""

    def test_gbp_sell_has_positive_net_cad(self, _loaded_hsbc):
        gbp_sells = [t for t in _loaded_hsbc if t.currency == "GBP" and t.action == "SELL"]
        assert len(gbp_sells) > 0
        for tx in gbp_sells:
            assert tx.net_cad is not None
            assert tx.net_cad > 0, "GBP sell should produce positive CAD proceeds"

    def test_usd_sell_has_positive_net_cad(self, _loaded_hsbc):
        usd_sells = [t for t in _loaded_hsbc if t.currency == "USD" and t.action == "SELL"]
        assert len(usd_sells) > 0
        for tx in usd_sells:
            assert tx.net_cad is not None
            assert tx.net_cad > 0


class TestPortfolioWithMultiCurrency:
    """Dashboard loads and produces valid data with mixed-currency holdings."""

    def test_portfolio_200(self, client, _loaded_hsbc):
        r = client.get("/api/portfolio")
        assert r.status_code == 200
        data = r.json()
        assert "error" not in data or data.get("error") is not True

    def test_transactions_include_foreign_currencies(self, client, _loaded_hsbc):
        r = client.get("/api/transactions")
        data = r.json()
        currencies = {t["currency"] for t in data}
        assert "GBP" in currencies, f"Expected GBP in {currencies}"
        assert "JPY" in currencies, f"Expected JPY in {currencies}"
        assert len(currencies) >= 5, f"Expected 5+ currencies, got {currencies}"

    def test_combined_totals_non_zero(self, client, _loaded_hsbc):
        r = client.get("/api/portfolio")
        data = r.json()
        combined = data["combined"]
        total = (combined.get("total_equity_cad", 0) or 0) + (combined.get("total_equity_usd", 0) or 0)
        assert total != 0, "Combined equity should be non-zero with holdings"

    def test_all_periods_200(self, client, _loaded_hsbc):
        for period in ["1m", "3m", "6m", "ytd", "1y", "all"]:
            r = client.get(f"/api/portfolio?period={period}")
            assert r.status_code == 200, f"period={period} failed"
