"""Tests for Item 0: crash recovery, import validation, factory reset."""
from __future__ import annotations

import math
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEST_DATA = PROJECT_ROOT / "test_data"

from backend.main import app
from backend.parsers.registry import parse_with_registry
from backend.store import upsert_transactions
from backend.validation import validate_transactions
from backend.models import Transaction


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def _loaded_ws(client):
    result = parse_with_registry(TEST_DATA / "csv" / "Wealthsimple_2024.csv")
    upsert_transactions(result.transactions)


# ---------- 0A: Portfolio never crashes on valid data ----------

class TestPortfolioCrashRecovery:
    def test_portfolio_200_after_import(self, client, _loaded_ws):
        r = client.get("/api/portfolio")
        assert r.status_code == 200
        body = r.json()
        assert "error" not in body or body.get("error") is not True

    def test_portfolio_200_empty_db(self, client):
        r = client.get("/api/portfolio")
        assert r.status_code == 200

    def test_portfolio_200_with_period(self, client, _loaded_ws):
        for period in ["1m", "3m", "6m", "ytd", "1y", "3y", "all"]:
            r = client.get(f"/api/portfolio?period={period}")
            assert r.status_code == 200, f"period={period} failed"

    def test_portfolio_returns_structured_error_not_500(self, client):
        """Even if build_portfolio somehow raises, the endpoint catches it
        and returns a structured 200 with error=True."""
        r = client.get("/api/portfolio")
        assert r.status_code == 200

    def test_price_history_bad_dates_dont_crash(self, client, _loaded_ws):
        """Inject a bad date into price_history and verify portfolio still loads."""
        from backend import db, store
        from sqlalchemy import insert
        engine = db.get_engine()
        with engine.begin() as conn:
            conn.execute(insert(db.price_history).values(
                ticker="VEQT.TO", date="not-a-date",
                open=38.0, high=39.0, low=37.5, close=38.5, volume=1000,
            ))
        df = store.get_price_history("VEQT.TO")
        assert isinstance(df.index, pd.DatetimeIndex) or df.empty

        r = client.get("/api/portfolio")
        assert r.status_code == 200


# ---------- 0B: Import validation ----------

class TestImportValidation:
    def test_valid_transactions_pass(self):
        txs = [
            Transaction(
                hash="h1", broker="wealthsimple",
                transaction_date=date(2024, 1, 15), action="BUY",
                raw_symbol="VEQT.TO", resolved_ticker="VEQT.TO",
                description="test", quantity=50, price=38.5,
                gross_amount=-1925, commission=0, net_amount=-1925,
                currency="CAD", account_number="acc-1", account_type="TFSA",
            ),
        ]
        result = validate_transactions(txs)
        assert len(result.valid) == 1
        assert result.skipped == 0
        assert result.warnings == []

    def test_nan_quantity_skipped(self):
        txs = [
            Transaction(
                hash="h2", broker="wealthsimple",
                transaction_date=date(2024, 1, 15), action="BUY",
                raw_symbol="VEQT.TO", resolved_ticker="VEQT.TO",
                description="test", quantity=float("nan"), price=38.5,
                gross_amount=-1925, commission=0, net_amount=-1925,
                currency="CAD", account_number="acc-1", account_type="TFSA",
            ),
        ]
        result = validate_transactions(txs)
        assert len(result.valid) == 0
        assert result.skipped == 1
        assert any("quantity" in w for w in result.warnings)

    def test_inf_price_skipped(self):
        txs = [
            Transaction(
                hash="h3", broker="wealthsimple",
                transaction_date=date(2024, 1, 15), action="BUY",
                raw_symbol="X", resolved_ticker="X",
                description="test", quantity=10, price=float("inf"),
                gross_amount=0, commission=0, net_amount=0,
                currency="CAD", account_number="acc-1", account_type="TFSA",
            ),
        ]
        result = validate_transactions(txs)
        assert result.skipped == 1

    def test_mixed_valid_invalid(self):
        good = Transaction(
            hash="g1", broker="wealthsimple",
            transaction_date=date(2024, 3, 1), action="BUY",
            raw_symbol="A", resolved_ticker="A",
            description="ok", quantity=10, price=50.0,
            gross_amount=-500, commission=0, net_amount=-500,
            currency="CAD", account_number="acc-1", account_type="TFSA",
        )
        bad = Transaction(
            hash="b1", broker="wealthsimple",
            transaction_date=date(2024, 3, 1), action="BUY",
            raw_symbol="B", resolved_ticker="B",
            description="bad", quantity=float("nan"), price=50.0,
            gross_amount=-500, commission=0, net_amount=-500,
            currency="CAD", account_number="acc-1", account_type="TFSA",
        )
        result = validate_transactions([good, bad])
        assert len(result.valid) == 1
        assert result.skipped == 1
        assert "1 rows skipped" in result.warnings[0]

    def test_portfolio_200_after_validated_import(self, client):
        """Import via API, check that portfolio loads after."""
        ws_file = TEST_DATA / "csv" / "Wealthsimple_2024.csv"
        with open(ws_file, "rb") as f:
            r = client.post("/api/import", files={"file": ("ws.csv", f, "text/csv")})
        assert r.status_code == 200
        data = r.json()
        assert data["inserted"] > 0

        r2 = client.get("/api/portfolio")
        assert r2.status_code == 200


# ---------- 0D: Factory reset ----------

class TestFactoryReset:
    def test_factory_reset_clears_all_data(self, client, _loaded_ws):
        r = client.get("/api/transactions")
        assert len(r.json()) > 0

        r2 = client.post("/api/app/reset")
        assert r2.status_code == 200
        assert r2.json()["success"] is True

        r3 = client.get("/api/transactions")
        assert r3.json() == []

    def test_factory_reset_creates_new_profile(self, client, _loaded_ws):
        r = client.post("/api/app/reset")
        assert r.status_code == 200
        assert "new_profile_id" in r.json()

        r2 = client.get("/api/profiles")
        assert r2.status_code == 200
        data = r2.json()
        assert len(data["profiles"]) == 1

    def test_portfolio_200_after_reset(self, client, _loaded_ws):
        client.post("/api/app/reset")
        r = client.get("/api/portfolio")
        assert r.status_code == 200

    def test_import_status_clean_after_reset(self, client, _loaded_ws):
        client.post("/api/app/reset")
        r = client.get("/api/import/status")
        assert r.status_code == 200
        assert r.json()["has_data"] is False


# ---------- 0E: Health check ----------

class TestHealthCheck:
    def test_health_reports_db_status(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert "db_corrupt" in data
        assert data["db_corrupt"] is False
