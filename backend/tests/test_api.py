"""API endpoint tests using FastAPI's TestClient."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEST_DATA = PROJECT_ROOT / "test_data"

from backend.main import app
from backend.parsers.registry import parse_with_registry
from backend.store import upsert_transactions


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def _loaded_ws(client):
    """Import Wealthsimple fixture into the test DB."""
    result = parse_with_registry(TEST_DATA / "csv" / "Wealthsimple_2024.csv")
    upsert_transactions(result.transactions)


@pytest.fixture
def _loaded_multi(client):
    """Import both WS and RBC fixtures."""
    ws = parse_with_registry(TEST_DATA / "csv" / "Wealthsimple_2024.csv")
    upsert_transactions(ws.transactions)
    rbc = parse_with_registry(TEST_DATA / "csv" / "RBC_DirectInvesting_2024.csv")
    upsert_transactions(rbc.transactions)


class TestTransactionsEndpoint:
    def test_empty_returns_200(self, client):
        r = client.get("/api/transactions")
        assert r.status_code == 200
        assert r.json() == []

    def test_returns_correct_shape(self, client, _loaded_ws):
        r = client.get("/api/transactions")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 20
        tx = data[0]
        assert "transaction_date" in tx
        assert "action" in tx
        assert "broker" in tx
        assert "currency" in tx
        assert "net_amount" in tx

    def test_filter_by_broker(self, client, _loaded_multi):
        r = client.get("/api/transactions?broker=wealthsimple")
        data = r.json()
        assert all(t["broker"] == "wealthsimple" for t in data)
        assert len(data) == 20

        r2 = client.get("/api/transactions?broker=rbc")
        data2 = r2.json()
        assert all(t["broker"] == "rbc" for t in data2)
        assert len(data2) == 20

    def test_filter_by_date_range(self, client, _loaded_ws):
        r = client.get("/api/transactions?date_from=2024-06-01&date_to=2024-08-31")
        data = r.json()
        assert len(data) > 0
        for t in data:
            d = t["transaction_date"]
            assert "2024-06-01" <= d <= "2024-08-31"

    def test_search_by_ticker(self, client, _loaded_ws):
        r = client.get("/api/transactions?search=VEQT")
        data = r.json()
        assert len(data) > 0
        for t in data:
            found = (
                ("VEQT" in (t.get("raw_symbol") or "").upper())
                or ("VEQT" in (t.get("resolved_ticker") or "").upper())
                or ("VEQT" in (t.get("description") or "").upper())
            )
            assert found

    def test_filter_by_action(self, client, _loaded_ws):
        r = client.get("/api/transactions?action=BUY")
        data = r.json()
        assert len(data) > 0
        assert all(t["action"] == "BUY" for t in data)

    def test_filter_by_currency(self, client, _loaded_ws):
        r = client.get("/api/transactions?currency=USD")
        data = r.json()
        assert all(t["currency"] == "USD" for t in data)


class TestTransactionSourcesEndpoint:
    def test_empty_returns_empty_list(self, client):
        r = client.get("/api/transactions/sources")
        assert r.status_code == 200
        assert r.json() == []

    def test_returns_correct_brokers(self, client, _loaded_multi):
        r = client.get("/api/transactions/sources")
        data = r.json()
        assert "wealthsimple" in data
        assert "rbc" in data
        assert len(data) == 2
