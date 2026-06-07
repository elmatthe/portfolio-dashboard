"""Item 4 Step 6 — PDF table extraction wired into the universal pipeline.

Covers the generic PDF lane (pdfplumber `extract_tables` → table_extract →
classify → Transaction) plus two guarantees that must not regress:
  * named PDF parsers (RBC / TD / CIBC) still win auto-detection — the generic
    lane never intercepts a file a named parser can read, and
  * a borderless, table-less PDF degrades to the text fallback without crashing.
"""
from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEST_DATA = PROJECT_ROOT / "test_data"
GENERIC_PDF = TEST_DATA / "generic" / "Generic_Transactions_2024.pdf"

from backend.import_engine.diagnostics import pop_last_diagnostics
from backend.import_engine.readers import read_pdf
from backend.parsers.generic import GenericParser
from backend.parsers.registry import detect_broker, read_content_sample
from backend.validation import validate_transactions

NAMED_PDF_FIXTURES = [
    ("pdf/RBC_DirectInvesting_2024.pdf", "rbc"),
    ("pdf/TD_DirectInvesting_2024.pdf", "td"),
    ("pdf/CIBC_InvestorsEdge_2024.pdf", "cibc"),
]


# --------------------------------------------------------------------------- #
# Generic PDF parses end-to-end through the full pipeline                      #
# --------------------------------------------------------------------------- #

def test_generic_pdf_parses_end_to_end():
    txs = GenericParser().parse(GENERIC_PDF)
    assert len(txs) == 5
    assert all(t.broker == "generic" for t in txs)
    assert [t.action for t in txs] == ["BUY", "SELL", "DIVIDEND", "CONTRIBUTION", "BUY"]
    # Every emitted row is safe to persist (passes Item 0 validation).
    vr = validate_transactions(txs)
    assert vr.skipped == 0
    assert len(vr.valid) == 5


def test_generic_pdf_diagnostics():
    GenericParser().parse(GENERIC_PDF)
    d = pop_last_diagnostics()
    assert d is not None
    assert d.fmt == "pdf"
    assert d.header_row_index == 3          # 3-row preamble skipped
    assert d.persisted_rows == 5
    assert d.counts_consistent
    assert d.state_counts["confident"] == 5
    assert any(e.field == "transaction_date" for e in d.field_map)


def test_generic_pdf_multipage_header_dedup():
    """The header repeats atop page 2; suppression must fire on the joined grid."""
    d_pre = read_pdf(GENERIC_PDF)[0]
    assert d_pre.extras["n_pages"] == 2          # genuinely multi-page
    assert d_pre.extras["text_fallback"] is False  # bordered table, not text path

    GenericParser().parse(GENERIC_PDF)
    d = pop_last_diagnostics()
    assert d.n_repeated_headers_suppressed >= 1   # page-2 header deduplicated
    assert d.total_rows == 5                       # 6 rows of data minus 1 repeat


# --------------------------------------------------------------------------- #
# Named PDF parsers still win — generic never intercepts them                  #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("rel,expected", NAMED_PDF_FIXTURES)
def test_named_pdf_routes_to_named_parser(rel, expected):
    f = TEST_DATA / rel
    sample = read_content_sample(f)
    assert GenericParser.detect(f, sample) < 0.50
    broker, conf = detect_broker(f)
    assert broker == expected, f"{rel} routed to {broker} (conf {conf}), not {expected}"


def test_generic_detect_on_pdf_is_low():
    assert GenericParser.detect(GENERIC_PDF, "") == pytest.approx(0.12)
    assert GenericParser.detect(GENERIC_PDF, "") < 0.50


# --------------------------------------------------------------------------- #
# Text-only (no detectable table) PDF falls back without crashing              #
# --------------------------------------------------------------------------- #

def _write_textonly_pdf(path: Path) -> Path:
    """A PDF with drawn text strings and NO ruled table → extract_tables() empty."""
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter

    c = canvas.Canvas(str(path), pagesize=letter)
    y = 720
    for line in (
        "Maplewood Securities",
        "Account Statement",
        "Date        Type      Symbol    Amount      Currency",
        "2024-06-01  Buy       AAPL      -1500.00    USD",
        "2024-06-15  Dividend  AAPL      18.25       USD",
    ):
        c.drawString(72, y, line)
        y -= 18
    c.showPage()
    c.save()
    return path


def test_textonly_pdf_falls_back_without_crashing(tmp_path):
    f = _write_textonly_pdf(tmp_path / "textonly.pdf")

    tables = read_pdf(f)
    assert tables and tables[0].fmt == "pdf"
    assert tables[0].extras["text_fallback"] is True  # no ruled table → text path
    assert tables[0].n_rows >= 1

    # The parser must not raise on a borderless PDF, whatever it manages to map.
    txs = GenericParser().parse(f)
    assert isinstance(txs, list)
