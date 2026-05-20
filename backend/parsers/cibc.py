"""CIBC Investor's Edge — CSV (and PDF in Step 6).

Quirks:
- 4-line metadata header before column row.
- Column names differ from RBC: `Trade Date / Transaction Type / Security /
  Shares/Units / Trade Price / Traded Currency / Trade Amount /
  Commission & Fees / Net Settlement / FX Rate / CAD Equivalent /
  Registered Account`.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import ClassVar

import pandas as pd

from backend.models import Transaction
from backend.parsers.base import BaseParser
from backend.parsers.rbc import _find_csv_header_row, _rows_to_transactions
from backend.parsers.registry import _register

logger = logging.getLogger(__name__)


@_register
class CIBCParser(BaseParser):
    BROKER_NAME: ClassVar[str] = "CIBC Investor's Edge"
    BROKER_KEY: ClassVar[str] = "cibc"
    SUPPORTED_FORMATS: ClassVar[list[str]] = ["csv", "pdf"]

    @classmethod
    def detect(cls, file_path: str | Path, content_sample: str) -> float:
        ext = Path(file_path).suffix.lower()
        s = content_sample.lower()
        if ext == ".csv":
            if "cibc investor" in s:
                return 0.95
            if "trade date" in s and "registered account" in s and "net settlement" in s:
                return 0.8
        if ext == ".pdf":
            try:
                import pdfplumber
                with pdfplumber.open(file_path) as pdf:
                    if pdf.pages:
                        text = (pdf.pages[0].extract_text() or "").lower()
                        if "cibc investor" in text:
                            return 0.95
                        if "cibc" in text:
                            return 0.7
            except Exception:
                return 0.0
        return 0.0

    def parse(self, file_path: str | Path) -> list[Transaction]:
        path = Path(file_path)
        ext = path.suffix.lower()
        if ext == ".csv":
            return _parse_cibc_csv(path)
        if ext == ".pdf":
            return _parse_cibc_pdf(path)
        return []


def _parse_cibc_csv(path: Path) -> list[Transaction]:
    text = path.read_text(encoding="utf-8", errors="replace")
    account_number = "cibc"
    for line in text.splitlines()[:4]:
        m = re.search(r"Account Number:\s*([\w-]+)", line)
        if m:
            account_number = m.group(1)
            break
    header_idx = _find_csv_header_row(text, must_contain=("Trade Date", "Net Settlement"))
    if header_idx is None:
        logger.warning("CIBC parser: no header row found in %s", path)
        return []
    df = pd.read_csv(path, skiprows=header_idx)
    return _rows_to_transactions(df, account_number, broker="cibc", default_currency="CAD")


def _parse_cibc_pdf(path: Path) -> list[Transaction]:
    """CIBC PDF has a dense 13-col table on a single page. Use pdfplumber
    with a tighter x_tolerance to prevent adjacent narrow columns from merging.
    Date format in this PDF is MM/DD/YYYY (line `01/04/2024` = Apr 1).
    """
    try:
        import pdfplumber
    except ImportError:
        logger.warning("pdfplumber required for CIBC PDF parsing")
        return []
    all_rows: list[list[str]] = []
    headers: list[str] | None = None
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables(table_settings={
                "vertical_strategy": "lines",
                "horizontal_strategy": "lines",
                "snap_tolerance": 3,
            }) or page.extract_tables()
            for table in tables or []:
                if not table:
                    continue
                if headers is None:
                    headers = [str(c or "").strip() for c in table[0]]
                    data_rows = table[1:]
                else:
                    first_cells = [str(c or "").strip() for c in table[0]]
                    data_rows = table[1:] if first_cells == headers else table
                for row in data_rows:
                    if not any(row):
                        continue
                    all_rows.append([str(c or "").strip() for c in row])
    if not headers or not all_rows:
        return []
    df = pd.DataFrame(all_rows, columns=headers)
    # Rename CIBC's terse PDF headers to ones the shared converter recognises.
    rename_map = {
        "Date": "Trade Date", "Txn": "Transaction Type", "Ticker": "Security",
        "Name": "Security Description", "Shares": "Shares/Units",
        "Price": "Trade Price", "Ccy": "Traded Currency", "Amount": "Trade Amount",
        "Comm": "Commission & Fees", "Net": "Net Settlement", "FX": "FX Rate",
        "CAD": "CAD Equivalent", "Acct": "Registered Account",
    }
    df.columns = [rename_map.get(c.strip(), c) for c in df.columns]
    return _rows_to_transactions(df, "cibc", broker="cibc", default_currency="CAD")
