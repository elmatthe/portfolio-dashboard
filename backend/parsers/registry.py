"""Parser registry + auto-detection pipeline.

Per CLAUDE_CODE_INSTRUCTIONS §2.2:
    1. Read first ~1 KB (text) or first sheet row (XLSX)
    2. Run all registered `detect()` methods
    3. Pick the parser with the highest confidence score (≥ 0.5)
    4. If no parser scores ≥ 0.5, fall back to GenericParser
    5. Log the detected broker name + confidence

The registry is populated by importing each parser module. Order matters
only for ties; we sort by score descending then by registration order.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Type

from backend.fx import get_fx_service
from backend.models import Transaction
from backend.parsers.base import BaseParser, ParserResult
from backend.parsers._common import read_text_sample

logger = logging.getLogger(__name__)


# Lazy-build the registry: import-time dependency cycles bite when each
# parser imports from backend.parsers, so we register classes one-by-one
# after import via _register().
BROKER_PARSERS: dict[str, Type[BaseParser]] = {}


def _register(cls: Type[BaseParser]) -> Type[BaseParser]:
    """Decorator-style registration. Keyed by the parser's BROKER_KEY."""
    if not cls.BROKER_KEY:
        raise ValueError(f"{cls.__name__} must set BROKER_KEY")
    BROKER_PARSERS[cls.BROKER_KEY] = cls
    return cls


_PARSER_MODULES = (
    # v0.2.0 baseline — registered first so tie-breaks favor them
    "questrade",
    "wealthsimple",
    # v0.3.0 new brokers — order matches §7 implementation order
    "interactive",
    "rbc",
    "cibc",
    "td",
    "bmo",
    "scotiabank",
    "nationalbank",
    "fidelity",
    "hsbc",
    # Fallback
    "generic",
)


def _populate_registry() -> None:
    """Import every parser module so the @_register decorator fires.

    Tolerant of not-yet-implemented modules during the v0.3.0 build (steps
    4–6 add them) — missing modules are logged at debug level and skipped.
    Safe to call repeatedly; assignments to BROKER_PARSERS are idempotent.
    """
    if BROKER_PARSERS:
        return
    for mod_name in _PARSER_MODULES:
        try:
            __import__(f"backend.parsers.{mod_name}", fromlist=["_"])
        except ModuleNotFoundError as e:
            # Only swallow when the missing module is the parser itself —
            # let downstream import errors surface so we don't hide real bugs.
            if e.name and e.name.endswith(f".{mod_name}"):
                logger.debug("Parser module %s not yet implemented — skipping", mod_name)
                continue
            raise


def read_content_sample(file_path: str | Path) -> str:
    """Read enough of a file for detection. For XLSX we let detect() handle
    the binary case; here we just return the text head (empty for binary)."""
    p = Path(file_path)
    if p.suffix.lower() in (".xlsx", ".xlsm", ".xls", ".pdf"):
        return ""
    return read_text_sample(p, max_bytes=4096)


def detect_broker(file_path: str | Path) -> tuple[str, float]:
    """Pick the parser with the highest confidence score.

    Returns (broker_key, confidence). Falls back to ("generic", 0.0) if no
    parser scores ≥ 0.5.
    """
    _populate_registry()
    sample = read_content_sample(file_path)
    best_key = "generic"
    best_score = 0.0
    for key, cls in BROKER_PARSERS.items():
        try:
            score = float(cls.detect(file_path, sample))
        except Exception as e:
            logger.debug("detect(%s) raised: %s", cls.__name__, e)
            continue
        if score > best_score:
            best_score = score
            best_key = key
    if best_score < 0.5:
        return "generic", best_score
    return best_key, best_score


def parse_with_registry(file_path: str | Path) -> ParserResult:
    """Auto-detect and parse. Returns ParserResult(transactions, broker_key, fmt, confidence).

    After parsing, fills `fx_rate_to_cad` and `net_cad` on any transaction whose
    parser left them blank (Questrade/Wealthsimple legacy parsers don't carry
    in-file FX columns, so they always defer to FXService). `populate_transaction`
    is idempotent — it only sets fields still set to None.
    """
    _populate_registry()
    broker_key, confidence = detect_broker(file_path)
    parser_cls = BROKER_PARSERS.get(broker_key)
    if parser_cls is None:
        # Fail-fast if even the generic fallback isn't registered (PyInstaller
        # hiddenimports gap). Raising here is friendlier than a KeyError mid-import.
        if "generic" not in BROKER_PARSERS:
            raise RuntimeError(
                "Parser registry missing the generic fallback. "
                f"Registered: {sorted(BROKER_PARSERS.keys())}. "
                "Check backend.spec hiddenimports if running a PyInstaller build."
            )
        parser_cls = BROKER_PARSERS["generic"]
    txs = parser_cls().parse(file_path)

    fx = get_fx_service()
    for t in txs:
        fx.populate_transaction(t)

    fmt = Path(file_path).suffix.lower().lstrip(".") or "unknown"
    logger.info(
        "Detected %s (%s) at confidence %.2f — parsed %d transactions",
        broker_key, fmt, confidence, len(txs),
    )
    return ParserResult(transactions=txs, broker_key=broker_key, fmt=fmt, confidence=confidence)
