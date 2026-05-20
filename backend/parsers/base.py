"""Parser interface that every broker implementation conforms to.

Per CLAUDE_CODE_INSTRUCTIONS §2.1:
    class BaseParser:
        BROKER_NAME: str                # human-readable, e.g. "RBC Direct Investing"
        BROKER_KEY: str                 # registry key, lowercase, e.g. "rbc"
        SUPPORTED_FORMATS: list[str]    # subset of {"csv", "tsv", "xlsx", "pdf"}

        @classmethod
        def detect(cls, file_path, content_sample) -> float: ...
        def parse(self, file_path) -> list[Transaction]: ...
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from backend.models import Transaction


@dataclass
class ParserResult:
    """What a parser returns when invoked through the registry."""

    transactions: list[Transaction]
    broker_key: str
    fmt: str  # "csv" | "tsv" | "xlsx" | "pdf"
    confidence: float


class BaseParser:
    """Abstract base. Subclasses set the three class-level constants and
    implement `detect` (classmethod) and `parse` (instance method)."""

    BROKER_NAME: ClassVar[str] = ""
    BROKER_KEY: ClassVar[str] = ""
    SUPPORTED_FORMATS: ClassVar[list[str]] = []

    @classmethod
    def detect(cls, file_path: str | Path, content_sample: str) -> float:
        """Confidence score 0.0–1.0 that this parser handles the file.

        Implementations inspect `file_path` (extension) and `content_sample`
        (first ~2 KB of bytes decoded as text) and return:
            - 1.0 for a definitive match (e.g. broker name in header)
            - 0.5–0.9 for structural matches (column names, delimiter, sheet name)
            - 0.0 for no match
        """
        return 0.0

    def parse(self, file_path: str | Path) -> list[Transaction]:
        """Read the file and emit normalized `Transaction` rows."""
        raise NotImplementedError(f"{self.__class__.__name__} must implement parse()")
