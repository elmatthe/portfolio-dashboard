"""Wealthsimple parser — v0.2.0 logic, wrapped in the new BaseParser interface.

DOES NOT modify the existing Wealthsimple parsing functions in backend.parser
— this is a thin adapter that calls them. Profile 6 regression depends on
zero behaviour change here.
"""
from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from backend import parser as legacy
from backend.models import Transaction
from backend.parsers.base import BaseParser
from backend.parsers.registry import _register


@_register
class WealthsimpleParser(BaseParser):
    """Wealthsimple Activities export (CSV) and statement PDF.

    Quirks (handled in legacy module — see backend/parser.py):
    - Account column carries values like "TFSA-9901" — type-prefix is split
      on '-' to map to AccountType.
    - Amounts can use "(123.45)" for negatives.
    """

    BROKER_NAME: ClassVar[str] = "Wealthsimple"
    BROKER_KEY: ClassVar[str] = "wealthsimple"
    SUPPORTED_FORMATS: ClassVar[list[str]] = ["csv", "pdf"]

    @classmethod
    def detect(cls, file_path: str | Path, content_sample: str) -> float:
        ext = Path(file_path).suffix.lower()
        if ext == ".csv":
            # Wealthsimple CSVs have Date / Activity / Symbol / Quantity / Price / Amount
            lower = content_sample.lower()
            if "activity" in lower and "amount" in lower and "date" in lower:
                # Distinguish from Fidelity (which has "Activity" too) by symbol column
                if "symbol" in lower:
                    return 0.9
        if ext == ".pdf":
            if "wealthsimple" in content_sample.lower():
                return 0.95
            # PDF: peek via the legacy detector which reads the actual PDF text
            try:
                fmt = legacy.detect_broker_and_format(file_path)
                return 0.95 if fmt.broker == "wealthsimple" else 0.0
            except Exception:
                return 0.0
        return 0.0

    def parse(self, file_path: str | Path) -> list[Transaction]:
        ext = Path(file_path).suffix.lower()
        if ext == ".csv":
            return legacy.parse_wealthsimple_csv(file_path)
        if ext == ".pdf":
            return legacy.parse_wealthsimple_pdf(file_path)
        raise ValueError(f"WealthsimpleParser: unsupported extension {ext}")
