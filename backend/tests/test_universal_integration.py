"""Item 4 Step 8 — universal-import integration / regression.

Two invariants are guarded here:

1. **Named parsers still win.** Every one of the 11 bundled named-broker
   fixtures must detect at >= the review threshold and route to its OWN parser,
   never to the generic fallback. This is the single most important regression
   for the universal lane — a generic parser that started swallowing named
   files would be a silent data-quality disaster.

2. **Generic rows feed every downstream system.** A messy, no-broker CSV taken
   end-to-end through /api/import/preview -> /api/import/confirm must land real
   transactions that the portfolio, transactions, currency-exposure, and
   attribution surfaces all consume without error — and re-importing the same
   file must dedup to zero. The app must never be brick-able by a generic import.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEST_DATA = PROJECT_ROOT / "test_data"
MESSY = TEST_DATA / "generic" / "Messy_Generic_2024.csv"

from backend.import_engine import preview as import_preview
from backend.parsers.registry import detect_broker
from backend.models import ResolvedTicker

# Every named-broker fixture in the repo, with the parser key it MUST route to.
# (CSV + XLSX cover all 11 named institutions; the PDF fixtures re-cover three
# of them in a second format.)
NAMED_FIXTURES: list[tuple[str, str]] = [
    ("csv/CIBC_InvestorsEdge_2024.csv", "cibc"),
    ("csv/Fidelity_2024.csv", "fidelity"),
    ("csv/InteractiveBrokers_2024.csv", "interactive"),
    ("csv/NationalBank_2024.csv", "nationalbank"),
    ("csv/RBC_DirectInvesting_2024.csv", "rbc"),
    ("csv/TD_DirectInvesting_2024.csv", "td"),
    ("csv/Wealthsimple_2024.csv", "wealthsimple"),
    ("xlsx/BMO_InvestorLine_2024.xlsx", "bmo"),
    ("xlsx/HSBC_InvestDirect_2024.xlsx", "hsbc"),
    ("xlsx/Questrade_2024.xlsx", "questrade"),
    ("xlsx/Scotia_iTrade_2024.xlsx", "scotiabank"),
]


@pytest.fixture
def client():
    return TestClient(app)


# main is imported lazily inside fixtures so the autouse _isolated_db (conftest)
# has already repointed the engine before the app touches the store.
from backend.main import app


@pytest.fixture(autouse=True)
def _clean_sessions():
    import_preview.clear_sessions()
    yield
    import_preview.clear_sessions()


@pytest.fixture
def _offline_resolver(monkeypatch):
    """Resolve every ticker to itself, no network, no price fetch.

    Resolving (rather than leaving unresolved) lets the portfolio actually build
    holdings, so the currency-exposure assertion can read /api/portfolio as the
    plan intends. Prices stay None — that's fine, currency is carried regardless.
    """
    from backend import market_data

    monkeypatch.setattr(
        market_data,
        "resolve_ticker",
        lambda raw, desc=None: ResolvedTicker(
            raw_symbol=raw, resolved_ticker=raw.upper(), status="resolved"
        ),
    )


def _preview(client: TestClient, path: Path) -> dict:
    with open(path, "rb") as fh:
        r = client.post(
            "/api/import/preview", files={"file": (path.name, fh, "application/octet-stream")}
        )
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------- #
# Invariant 1 — named parsers never fall through to generic                     #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("rel_path,expected_key", NAMED_FIXTURES)
def test_named_fixture_detects_above_threshold(rel_path: str, expected_key: str):
    path = TEST_DATA / rel_path
    key, confidence = detect_broker(path)
    assert key == expected_key, f"{rel_path} routed to {key!r}, expected {expected_key!r}"
    assert key != "generic"
    assert confidence >= import_preview.REVIEW_CONFIDENCE_THRESHOLD, (
        f"{rel_path} detected at {confidence:.2f}, below review threshold "
        f"{import_preview.REVIEW_CONFIDENCE_THRESHOLD} — it would wrongly open the editor"
    )


@pytest.mark.parametrize("rel_path,expected_key", NAMED_FIXTURES)
def test_named_fixture_preview_short_circuits(client: TestClient, rel_path: str, expected_key: str):
    body = _preview(client, TEST_DATA / rel_path)
    assert body["mode"] == "named"
    assert body["needs_review"] is False
    assert "token" not in body  # named files never create a preview session


# --------------------------------------------------------------------------- #
# Invariant 2 — generic rows feed every downstream system                       #
# --------------------------------------------------------------------------- #

def test_generic_import_feeds_all_downstream_systems(client: TestClient, _offline_resolver):
    # 1. Preview the messy CSV: generic lane, editor would open.
    body = _preview(client, MESSY)
    assert body["mode"] == "generic"
    assert body["needs_review"] is True
    assert body["detected_broker"] == "generic"

    # 2. Confirm with NO overrides — accept the auto-mapping.
    confirm = client.post("/api/import/confirm", json={"token": body["token"]})
    assert confirm.status_code == 200, confirm.text
    result = confirm.json()
    assert result["inserted"] == 4
    assert result["import_diagnostics"] is not None

    # 3. Portfolio renders (200, real payload, not the recovery error shape).
    port = client.get("/api/portfolio")
    assert port.status_code == 200
    pdata = port.json()
    assert pdata.get("error") is not True
    assert "combined" in pdata and "holdings" in pdata

    # 4. Transactions surface carries the generic rows, tagged broker="generic".
    txs = client.get("/api/transactions", params={"broker": "generic"}).json()
    assert len(txs) == 4
    assert all(t["broker"] == "generic" for t in txs)

    # 5. Currency exposure: the portfolio's holdings include BOTH currencies the
    #    generic rows carried (USD from AAPL, CAD from VEQT.TO).
    holding_currencies = {h["currency"] for h in pdata["holdings"]}
    assert {"USD", "CAD"} <= holding_currencies, (
        f"currency exposure {holding_currencies} missing a generic-row currency"
    )
    # belt-and-suspenders: the source rows carried those same currencies
    assert {"USD", "CAD"} <= {t["currency"] for t in txs}

    # 6. Attribution computes without error.
    assert client.get("/api/attribution").status_code == 200


def test_generic_reimport_dedups_to_zero(client: TestClient, _offline_resolver):
    # First import.
    first = _preview(client, MESSY)
    c1 = client.post("/api/import/confirm", json={"token": first["token"]})
    assert c1.status_code == 200
    assert c1.json()["inserted"] == 4

    # Second pass: the confirmed layout is remembered (no editor), but the rows
    # are identical, so dedup holds them all back.
    second = _preview(client, MESSY)
    assert second["mode"] == "generic"
    assert second["reused_saved_mapping"] is True
    assert second["needs_review"] is False
    assert second["token"]

    c2 = client.post("/api/import/confirm", json={"token": second["token"]})
    assert c2.status_code == 200, c2.text
    out = c2.json()
    assert out["inserted"] == 0
    assert out["skipped_duplicates"] == 4

    # The app is still healthy after the duplicate import.
    assert client.get("/api/portfolio").status_code == 200
