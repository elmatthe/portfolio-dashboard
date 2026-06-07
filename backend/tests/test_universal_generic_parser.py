"""Item 4 Step 5 — GenericParser wired to the full import_engine pipeline."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEST_DATA = PROJECT_ROOT / "test_data"
MESSY = TEST_DATA / "generic" / "Messy_Generic_2024.csv"

from backend.import_engine.diagnostics import pop_last_diagnostics
from backend.main import app
from backend.models import ResolvedTicker
from backend.parsers.generic import GenericParser
from backend.parsers.registry import detect_broker, read_content_sample
from backend.validation import validate_transactions

NAMED_FIXTURES = [
    "csv/CIBC_InvestorsEdge_2024.csv",
    "csv/Fidelity_2024.csv",
    "csv/InteractiveBrokers_2024.csv",
    "csv/NationalBank_2024.csv",
    "csv/RBC_DirectInvesting_2024.csv",
    "csv/TD_DirectInvesting_2024.csv",
    "csv/Wealthsimple_2024.csv",
    "xlsx/BMO_InvestorLine_2024.xlsx",
    "xlsx/HSBC_InvestDirect_2024.xlsx",
    "xlsx/Questrade_2024.xlsx",
    "xlsx/Scotia_iTrade_2024.xlsx",
]


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def _no_network(monkeypatch):
    """Keep import-endpoint tests hermetic: never call yfinance for resolution."""
    from backend import market_data

    monkeypatch.setattr(
        market_data,
        "resolve_ticker",
        lambda raw, desc=None: ResolvedTicker(
            raw_symbol=raw, resolved_ticker=None, status="unresolved"
        ),
    )


def _write_csv(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# End-to-end through the full pipeline                                         #
# --------------------------------------------------------------------------- #

def test_messy_fixture_parses_end_to_end():
    txs = GenericParser().parse(MESSY)
    assert len(txs) == 4
    assert all(t.broker == "generic" for t in txs)
    assert [t.action for t in txs] == ["BUY", "SELL", "DIVIDEND", "BUY"]
    # Every emitted row survives Item 0 validation (safe to persist).
    vr = validate_transactions(txs)
    assert vr.skipped == 0
    assert len(vr.valid) == 4
    # Diagnostics describe what was identified.
    d = pop_last_diagnostics()
    assert d is not None
    assert d.detected_institution and d.detected_institution != ""
    assert d.header_row_index == 3
    assert d.persisted_rows == 4
    assert any(e.field == "transaction_date" for e in d.field_map)


def test_diagnostics_counts_consistent():
    GenericParser().parse(MESSY)
    d = pop_last_diagnostics()
    assert sum(d.state_counts.values()) == d.total_rows
    assert d.counts_consistent


# --------------------------------------------------------------------------- #
# PARTIAL / UNMAPPED rows are kept in diagnostics, never persisted             #
# --------------------------------------------------------------------------- #

def test_partial_row_in_diagnostics_not_persisted(tmp_path):
    f = _write_csv(
        tmp_path / "stripped.csv",
        "Date,Type,Symbol,Quantity,Price,Amount,Currency\n"
        "2024-01-05,Buy,AAPL,10,180.00,-1800.00,USD\n"
        "2024-02-10,Buy,MSFT,,,,USD\n",  # no qty/price/net → cannot complete a BUY
    )
    txs = GenericParser().parse(f)
    assert any(t.raw_symbol == "AAPL" for t in txs)
    assert not any(t.raw_symbol == "MSFT" for t in txs)  # partial → not persisted

    d = pop_last_diagnostics()
    assert d.state_counts["partial"] >= 1
    partial_notes = [n for n in d.row_notes if n.state == "partial"]
    assert partial_notes
    # The blocking field is identified and tied to a downstream calc.
    assert any("quantity" in g for n in partial_notes for g in n.missing_fields)
    assert any("ACB" in diag for n in partial_notes for diag in n.diagnostics)


def test_unmapped_row_kept_not_persisted_not_dropped(tmp_path):
    f = _write_csv(
        tmp_path / "unmapped.csv",
        "Date,Type,Symbol,Quantity,Price,Amount,Currency\n"
        "2024-01-05,Buy,AAPL,10,180.00,-1800.00,USD\n"
        ",Note,,,,,\n",  # no date, no value → cannot anchor
    )
    txs = GenericParser().parse(f)
    assert len(txs) == 1  # only the confident AAPL row persists

    d = pop_last_diagnostics()
    assert d.total_rows == 2  # the unmapped row was kept, not dropped
    assert d.state_counts["unmapped"] >= 1
    assert any(n.state == "unmapped" for n in d.row_notes)


# --------------------------------------------------------------------------- #
# Named parsers always win — generic never reaches 0.50                        #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("rel", NAMED_FIXTURES)
def test_named_fixtures_still_route_to_named_parser(rel):
    f = TEST_DATA / rel
    sample = read_content_sample(f)
    assert GenericParser.detect(f, sample) < 0.50
    broker, conf = detect_broker(f)
    assert broker != "generic", f"{rel} fell through to generic (conf {conf})"


def test_generic_detect_caps_below_threshold_on_messy():
    assert GenericParser.detect(MESSY, MESSY.read_text(encoding="utf-8")) < 0.50
    assert detect_broker(MESSY)[0] == "generic"


# --------------------------------------------------------------------------- #
# Endpoint integration: dedup, diagnostics surfaced, app not bricked          #
# --------------------------------------------------------------------------- #

def test_reimport_generic_file_inserts_zero(client, _no_network):
    with open(MESSY, "rb") as fh:
        r1 = client.post("/api/import", files={"file": ("Messy_Generic_2024.csv", fh, "text/csv")})
    assert r1.status_code == 200
    b1 = r1.json()
    assert b1["inserted"] == 4
    assert b1["import_diagnostics"] is not None  # diagnostics surfaced to the UI
    assert b1["import_diagnostics"]["state_counts"]["confident"] >= 1

    with open(MESSY, "rb") as fh:
        r2 = client.post("/api/import", files={"file": ("Messy_Generic_2024.csv", fh, "text/csv")})
    assert r2.status_code == 200
    assert r2.json()["inserted"] == 0  # dedup by SHA-256 hash


def test_named_import_has_no_diagnostics(client, _no_network):
    ws = TEST_DATA / "csv" / "Wealthsimple_2024.csv"
    with open(ws, "rb") as fh:
        r = client.post("/api/import", files={"file": ("ws.csv", fh, "text/csv")})
    assert r.status_code == 200
    body = r.json()
    assert body["inserted"] > 0
    assert body["import_diagnostics"] is None  # named-parser path unchanged


def test_generic_import_does_not_brick_portfolio(client, _no_network):
    with open(MESSY, "rb") as fh:
        r = client.post("/api/import", files={"file": ("m.csv", fh, "text/csv")})
    assert r.status_code == 200
    assert client.get("/api/portfolio").status_code == 200
