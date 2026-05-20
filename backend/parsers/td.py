"""TD Direct Investing — TSV (tab-separated) and PDF (Step 6).

Quirks:
- Tab-separated, NOT comma-separated.
- No metadata header block; column row is line 1.
- Extra `Order ID` column → captured as `reference_id`.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import ClassVar

import pandas as pd

from backend.models import Transaction
from backend.parsers.base import BaseParser
from backend.parsers.rbc import _rows_to_transactions
from backend.parsers.registry import _register

logger = logging.getLogger(__name__)


@_register
class TDParser(BaseParser):
    BROKER_NAME: ClassVar[str] = "TD Direct Investing"
    BROKER_KEY: ClassVar[str] = "td"
    SUPPORTED_FORMATS: ClassVar[list[str]] = ["csv", "tsv", "pdf"]

    @classmethod
    def detect(cls, file_path: str | Path, content_sample: str) -> float:
        ext = Path(file_path).suffix.lower()
        if ext in (".csv", ".tsv"):
            s = content_sample
            first_line = s.splitlines()[0] if s else ""
            if "\t" in first_line and "Company Name" in first_line and "Order ID" in first_line:
                return 0.9
            if "Company Name" in first_line and "Exch Rate" in first_line:
                return 0.7
        if ext == ".pdf":
            try:
                import pdfplumber
                with pdfplumber.open(file_path) as pdf:
                    if pdf.pages:
                        text = (pdf.pages[0].extract_text() or "").lower()
                        if "td direct investing" in text:
                            return 0.95
                        if "td" in text and "exch rate" in text:
                            return 0.7
            except Exception:
                return 0.0
        return 0.0

    def parse(self, file_path: str | Path) -> list[Transaction]:
        path = Path(file_path)
        ext = path.suffix.lower()
        if ext in (".csv", ".tsv"):
            df = pd.read_csv(path, sep="\t", encoding_errors="replace")
            return _rows_to_transactions(df, "td", broker="td", default_currency="CAD")
        if ext == ".pdf":
            return _parse_td_pdf(path)
        return []


def _parse_td_pdf(path: Path) -> list[Transaction]:
    """TD PDF has clean tables on every page. pdfplumber.extract_tables()
    returns the rows directly; we re-package them as a DataFrame and feed
    the shared row converter.
    """
    try:
        import pdfplumber
    except ImportError:
        logger.warning("pdfplumber required for TD PDF parsing")
        return []
    all_rows: list[list[str]] = []
    headers: list[str] | None = None
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                if not table:
                    continue
                if headers is None:
                    headers = [str(c or "").strip() for c in table[0]]
                    data_rows = table[1:]
                else:
                    # Subsequent pages repeat the header — only skip when it matches.
                    first_cells = [str(c or "").strip() for c in table[0]]
                    data_rows = table[1:] if first_cells == headers else table
                for row in data_rows:
                    if not any(row):
                        continue
                    all_rows.append([str(c or "").strip() for c in row])
    if not headers or not all_rows:
        return []
    df = pd.DataFrame(all_rows, columns=headers)
    # Replace the "Portfolio" column name with one our aliases recognise as account_type.
    df.columns = [("Account" if c.strip().lower() == "portfolio" else c) for c in df.columns]
    return _rows_to_transactions(df, "td", broker="td", default_currency="CAD")
