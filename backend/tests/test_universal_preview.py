"""Item 4 Step 7 — generic-lane mapping preview / confirm endpoints."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEST_DATA = PROJECT_ROOT / "test_data"
MESSY = TEST_DATA / "generic" / "Messy_Generic_2024.csv"
NAMED = TEST_DATA / "csv" / "Wealthsimple_2024.csv"

from backend.import_engine import preview as import_preview
from backend.main import app
from backend.models import ResolvedTicker


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clean_sessions():
    """Preview sessions are module-level; isolate every test."""
    import_preview.clear_sessions()
    yield
    import_preview.clear_sessions()


@pytest.fixture
def _no_network(monkeypatch):
    from backend import market_data

    monkeypatch.setattr(
        market_data,
        "resolve_ticker",
        lambda raw, desc=None: ResolvedTicker(
            raw_symbol=raw, resolved_ticker=None, status="unresolved"
        ),
    )


def _preview(client, path: Path) -> dict:
    with open(path, "rb") as fh:
        r = client.post("/api/import/preview", files={"file": (path.name, fh, "text/csv")})
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------- #
# Preview                                                                       #
# --------------------------------------------------------------------------- #

def test_preview_returns_token_and_field_map_for_generic(client):
    body = _preview(client, MESSY)
    assert body["mode"] == "generic"
    assert body["needs_review"] is True
    assert body["token"]
    assert body["detected_broker"] == "generic"
    assert body["detected_confidence"] < import_preview.REVIEW_CONFIDENCE_THRESHOLD
    # field_map covers the core fields, with a source column for the date.
    fields = {f["field"]: f for f in body["fields"]}
    assert "transaction_date" in fields
    assert fields["transaction_date"]["col_index"] is not None
    # editor scaffolding the UI needs
    assert body["source_columns"]
    assert len(body["sample_rows"]) > 0
    assert sum(body["row_state_counts"].values()) > 0


def test_preview_named_parser_short_circuits(client):
    body = _preview(client, NAMED)
    assert body["mode"] == "named"
    assert body["needs_review"] is False
    assert "token" not in body
    assert body["detected_confidence"] >= import_preview.REVIEW_CONFIDENCE_THRESHOLD


# --------------------------------------------------------------------------- #
# Confirm                                                                       #
# --------------------------------------------------------------------------- #

def test_confirm_with_token_imports_rows(client, _no_network):
    body = _preview(client, MESSY)
    r = client.post("/api/import/confirm", json={"token": body["token"]})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["inserted"] == 4
    assert out["import_diagnostics"] is not None
    assert client.get("/api/portfolio").status_code == 200


def test_confirm_with_override_unmapping_currency(client, _no_network):
    body = _preview(client, MESSY)
    # Drop the currency column; rows still import (currency defaults to CAD).
    r = client.post(
        "/api/import/confirm",
        json={"token": body["token"], "user_mapping": {"currency": -1}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["inserted"] == 4


def test_confirm_unknown_token_404(client):
    r = client.post("/api/import/confirm", json={"token": "deadbeefdeadbeef"})
    assert r.status_code == 404


def test_confirm_already_used_token_410(client, _no_network):
    body = _preview(client, MESSY)
    first = client.post("/api/import/confirm", json={"token": body["token"]})
    assert first.status_code == 200
    again = client.post("/api/import/confirm", json={"token": body["token"]})
    assert again.status_code == 410


# --------------------------------------------------------------------------- #
# Fingerprint memory: a confirmed layout is reused without re-prompting         #
# --------------------------------------------------------------------------- #

def test_confirmed_mapping_reused_on_second_preview(client, _no_network):
    first = _preview(client, MESSY)
    assert first["needs_review"] is True
    assert first.get("reused_saved_mapping", False) is False

    confirm = client.post("/api/import/confirm", json={"token": first["token"]})
    assert confirm.status_code == 200

    second = _preview(client, MESSY)
    assert second["mode"] == "generic"
    assert second["reused_saved_mapping"] is True
    assert second["needs_review"] is False  # same layout → no editor
    assert second["token"]  # still confirmable straight through
