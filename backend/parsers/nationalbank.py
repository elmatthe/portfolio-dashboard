"""National Bank Direct Brokerage — CSV with bilingual French/English headers.

Quirks:
- Column names use ' / ' to separate French and English versions, e.g.
  `Date d'exécution / Execution Date`. Our column aliases include the
  bilingual form, so the shared converter handles them transparently.
- 3-line metadata header before the column row.
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
class NationalBankParser(BaseParser):
    BROKER_NAME: ClassVar[str] = "National Bank Direct Brokerage"
    BROKER_KEY: ClassVar[str] = "nationalbank"
    SUPPORTED_FORMATS: ClassVar[list[str]] = ["csv"]

    @classmethod
    def detect(cls, file_path: str | Path, content_sample: str) -> float:
        if Path(file_path).suffix.lower() != ".csv":
            return 0.0
        s = content_sample.lower()
        if "banque nationale" in s or "national bank direct" in s:
            return 0.95
        if " / " in s and "type d'opération" in s:
            return 0.8
        return 0.0

    def parse(self, file_path: str | Path) -> list[Transaction]:
        path = Path(file_path)
        if path.suffix.lower() != ".csv":
            return []
        text = path.read_text(encoding="utf-8", errors="replace")
        account_number = "nationalbank"
        for line in text.splitlines()[:4]:
            m = re.search(r"(?:Compte|Account)[^\d]*([\d-]+)", line)
            if m:
                account_number = m.group(1)
                break
        header_idx = _find_csv_header_row(text, must_contain=("Execution Date", "Net"))
        if header_idx is None:
            logger.warning("NationalBank parser: no header row found in %s", path)
            return []
        df = pd.read_csv(path, skiprows=header_idx)
        return _rows_to_transactions(df, account_number, broker="nationalbank", default_currency="CAD")
