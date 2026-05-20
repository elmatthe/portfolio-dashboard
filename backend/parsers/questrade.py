"""Questrade parser — v0.2.0 logic, wrapped in the new BaseParser interface.

DOES NOT modify the existing Questrade parsing functions in backend.parser
— this is a thin adapter. Profile 6 regression depends on zero behaviour
change here.
"""
from __future__ import annotations

import warnings
from pathlib import Path
from typing import ClassVar

import pandas as pd

from backend import parser as legacy
from backend.models import Transaction
from backend.parsers.base import BaseParser
from backend.parsers.registry import _register


@_register
class QuestradeParser(BaseParser):
    """Questrade transaction export (XLSX, 'Activities' sheet)."""

    BROKER_NAME: ClassVar[str] = "Questrade"
    BROKER_KEY: ClassVar[str] = "questrade"
    SUPPORTED_FORMATS: ClassVar[list[str]] = ["xlsx"]

    @classmethod
    def detect(cls, file_path: str | Path, content_sample: str) -> float:
        ext = Path(file_path).suffix.lower()
        if ext not in (".xlsx", ".xlsm"):
            return 0.0
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                xl = pd.ExcelFile(file_path)
            if any(s.lower() == "activities" for s in xl.sheet_names):
                return 0.95
        except Exception:
            return 0.0
        return 0.0

    def parse(self, file_path: str | Path) -> list[Transaction]:
        return legacy.parse_questrade_xlsx(file_path)
