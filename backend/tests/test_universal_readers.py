"""Item 4 Step 2 — file readers + table/header extraction.

Covers:
  * `readers.read_tabular` on csv + xlsx (one RawTable per sheet).
  * `table_extract.extract` finding the real header row in every existing
    named-parser fixture (proves the extractor handles real broker layouts).
  * BMO's 4-row title preamble is skipped (header found at row 4).
  * A new MESSY generic fixture: preamble skipped, repeated header suppressed,
    subtotal/total footers dropped, only the 4 real data rows kept.
  * REGRESSION: every named fixture still routes to its NAMED parser — the new
    import_engine must NOT intercept files the named lane owns.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.import_engine.canonical import CanonicalField as F
from backend.import_engine.readers import read_tabular
from backend.import_engine.table_extract import extract, find_header_row
from backend.parsers.registry import detect_broker

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEST_DATA = PROJECT_ROOT / "test_data"

# fixture path → (expected named broker key, min distinct canonical fields the
# header extractor should recognize)
NAMED_FIXTURES: dict[str, tuple[str, int]] = {
    "csv/CIBC_InvestorsEdge_2024.csv": ("cibc", 4),
    "csv/Fidelity_2024.csv": ("fidelity", 4),
    "csv/InteractiveBrokers_2024.csv": ("interactive", 3),
    "csv/NationalBank_2024.csv": ("nationalbank", 4),
    "csv/RBC_DirectInvesting_2024.csv": ("rbc", 4),
    "csv/TD_DirectInvesting_2024.csv": ("td", 4),
    "csv/Wealthsimple_2024.csv": ("wealthsimple", 3),
    "xlsx/BMO_InvestorLine_2024.xlsx": ("bmo", 6),
    "xlsx/HSBC_InvestDirect_2024.xlsx": ("hsbc", 4),
    "xlsx/Questrade_2024.xlsx": ("questrade", 3),
    "xlsx/Scotia_iTrade_2024.xlsx": ("scotiabank", 4),
}


# --------------------------------------------------------------------------- #
# readers                                                                      #
# --------------------------------------------------------------------------- #

def test_read_tabular_csv_returns_single_table():
    tables = read_tabular(TEST_DATA / "csv" / "Wealthsimple_2024.csv")
    assert len(tables) == 1
    assert tables[0].fmt in ("csv", "tsv")
    assert tables[0].n_rows > 1


def test_read_tabular_xlsx_returns_sheets():
    tables = read_tabular(TEST_DATA / "xlsx" / "BMO_InvestorLine_2024.xlsx")
    assert len(tables) >= 1
    assert all(t.fmt == "xlsx" for t in tables)


def test_read_tabular_reads_pdf():
    # PDF was a placeholder rejection through Step 5; Step 6 wired pdfplumber in,
    # so read_tabular now returns a single concatenated RawTable for a PDF.
    tables = read_tabular(TEST_DATA / "pdf" / "RBC_DirectInvesting_2024.pdf")
    assert len(tables) == 1
    assert tables[0].fmt == "pdf"
    assert tables[0].n_rows > 1


# --------------------------------------------------------------------------- #
# header extraction across ALL real fixtures                                   #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("rel,expected", list(NAMED_FIXTURES.items()))
def test_extract_finds_header_in_real_fixtures(rel, expected):
    _broker, min_fields = expected
    et = extract(TEST_DATA / rel)
    assert et.header_row_index >= 0, f"{rel}: no header row found"
    assert len(et.matched_fields) >= min_fields, (
        f"{rel}: only matched {len(et.matched_fields)} fields "
        f"({sorted(f.value for f in et.matched_fields.values())})"
    )
    # Every located table must expose a date column. Some brokers (e.g. RBC CSV)
    # carry only a settlement date; mapping settlement→transaction_date when no
    # trade date exists is a Step 4 derivation, so accept either here.
    date_fields = {F.TRANSACTION_DATE, F.SETTLEMENT_DATE}
    assert date_fields & set(et.matched_fields.values()), f"{rel}: no date column"
    assert et.n_data_rows > 0, f"{rel}: no data rows extracted"


def test_bmo_preamble_skipped():
    """BMO xlsx has 4 title/preamble rows (0-3); real header is row 4."""
    et = extract(TEST_DATA / "xlsx" / "BMO_InvestorLine_2024.xlsx")
    assert et.header_row_index == 4
    assert et.n_preamble_skipped == 4
    got = set(et.matched_fields.values())
    for f in (F.TRANSACTION_DATE, F.ACTION, F.TICKER, F.QUANTITY, F.PRICE, F.NET_AMOUNT):
        assert f in got, f"BMO header missing {f}"


# --------------------------------------------------------------------------- #
# messy generic fixture                                                        #
# --------------------------------------------------------------------------- #

def test_messy_fixture_header_preamble_repeat_and_footers():
    et = extract(TEST_DATA / "generic" / "Messy_Generic_2024.csv")
    # 2 preamble lines + 1 blank line above the header → header at row 3.
    assert et.header_row_index == 3
    assert et.n_preamble_skipped == 3
    # The mid-file duplicate header row is suppressed…
    assert et.n_repeated_headers_suppressed == 1
    # …and the "Subtotal"/"Total" footer rows are dropped.
    assert et.n_footer_dropped == 2
    # Leaving exactly the 4 genuine data rows.
    assert et.n_data_rows == 4
    # Header recognized the canonical columns.
    got = set(et.matched_fields.values())
    for f in (F.TRANSACTION_DATE, F.ACTION, F.TICKER, F.QUANTITY, F.PRICE,
              F.NET_AMOUNT, F.CURRENCY):
        assert f in got, f"messy header missing {f}"


def test_find_header_row_headerless_fallback():
    """A grid with no recognizable header still returns a sensible first row."""
    rows = [["", ""], ["foo", "bar", "baz"], ["1", "2", "3"]]
    assert find_header_row(rows) == 1  # first row with >= 2 non-empty cells


# --------------------------------------------------------------------------- #
# REGRESSION: named fixtures are NOT intercepted by the generic engine         #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("rel,expected", list(NAMED_FIXTURES.items()))
def test_named_fixtures_still_route_to_named_parser(rel, expected):
    broker, _min = expected
    key, conf = detect_broker(TEST_DATA / rel)
    assert key == broker, f"{rel}: routed to {key!r} (conf {conf:.2f}), expected {broker!r}"
    assert key != "generic", f"{rel}: was hijacked by the generic lane"
