"""Generic fallback parser — last-resort heuristic for files no broker claimed.

Per §2.2 step 4: if no parser scores ≥ 0.5, fall back here. We try to guess
the delimiter and column layout, then run through the shared row converter.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import ClassVar

import pandas as pd

from backend.models import Transaction
from backend.parsers._common import read_text_sample, sniff_csv_delimiter
from backend.parsers.base import BaseParser
from backend.parsers.rbc import _rows_to_transactions
from backend.parsers.registry import _register

logger = logging.getLogger(__name__)


@_register
class GenericParser(BaseParser):
    BROKER_NAME: ClassVar[str] = "Generic / Unknown Broker"
    BROKER_KEY: ClassVar[str] = "generic"
    SUPPORTED_FORMATS: ClassVar[list[str]] = ["csv", "tsv"]

    @classmethod
    def detect(cls, file_path: str | Path, content_sample: str) -> float:
        # Generic never wins a positive detection — it's only used as the
        # registry fallback when nothing else clears 0.5.
        return 0.0

    def parse(self, file_path: str | Path) -> list[Transaction]:
        path = Path(file_path)
        ext = path.suffix.lower()
        if ext not in (".csv", ".tsv"):
            logger.warning("Generic parser cannot handle %s files", ext)
            return []
        sample = read_text_sample(path, max_bytes=4096)
        delim = sniff_csv_delimiter(sample)
        try:
            df = pd.read_csv(path, sep=delim, encoding_errors="replace")
        except Exception as e:
            logger.warning("Generic parser failed to read %s: %s", path, e)
            return []
        return _rows_to_transactions(df, "generic", broker="generic", default_currency="CAD")
