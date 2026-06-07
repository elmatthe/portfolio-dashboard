"""Generic fallback parser — the universal/intelligent import lane (Item 4).

The registry routes here ONLY when no named broker parser clears 0.50, so named
parsers always win. This is the last-resort lane that lets the app ingest a
transaction export from ANY brokerage/bank — or a hand-built CSV/XLSX — by:

    readers.read_tabular  → locate + decode the grid
    table_extract.extract → find the real table + header row (skip preamble,
                            footers, repeated headers)
    classify_columns      → alias + fuzzy + value-profile → field↔column map
    normalize_row         → clean each row, record derivations
    classify_row          → action map/infer + four-state per-row outcome

Only CONFIDENT and WITH_ASSUMPTIONS rows become `Transaction`s; those flow through
the SAME back half as every other import (FXService → Item 0 validation → SHA-256
dedup → store, run by the registry + `/api/import` endpoint). PARTIAL and UNMAPPED
rows are NEVER persisted and NEVER dropped — they are surfaced in
`ImportDiagnostics` for review.

`detect()` deliberately returns a low score (0.10–0.45): generic must never win
auto-detection over a named parser.

Note on `broker`: `Transaction.broker` is a fixed `Broker` Literal, so emitted
rows carry `broker="generic"`. The human-readable institution detected from the
file preamble is surfaced via `ImportDiagnostics.detected_institution` and each
row's `notes`, not by widening the typed vocabulary (out of scope for 0.7.0).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import ClassVar

from backend.fx import get_fx_service
from backend.models import Transaction
from backend.parsers._common import (
    compute_hash,
    guess_exchange,
    read_text_sample,
    sniff_csv_delimiter,
)
# `canonical` is pure data (no I/O), so it's cycle-safe at module load. The rest of
# the import_engine (readers → table_extract → classify_*) reaches back into
# `backend.parsers._common`, which `backend.parsers.__init__` is mid-importing when
# it loads THIS module — so those are imported lazily inside parse(), by which time
# every module is fully initialized. Same late-import trick registry.py/parser.py use.
from backend.import_engine.canonical import CanonicalField as F
from backend.parsers.base import BaseParser
from backend.parsers.registry import _register

logger = logging.getLogger(__name__)

_TABULAR_EXT = (".csv", ".tsv", ".xls", ".xlsx", ".xlsm", ".pdf")

# Institutions worth naming if they appear anywhere in the file preamble/header.
_INSTITUTION_KEYWORDS = (
    "rbc", "td direct", "td", "bmo", "scotia", "cibc", "national bank",
    "questrade", "wealthsimple", "interactive brokers", "fidelity", "hsbc",
    "vanguard", "charles schwab", "schwab", "robinhood", "e*trade", "etrade",
    "tangerine", "desjardins", "qtrade", "disnat",
)

_GENERIC_LABEL = "Imported (Generic)"


@_register
class GenericParser(BaseParser):
    BROKER_NAME: ClassVar[str] = "Generic / Unknown Broker"
    BROKER_KEY: ClassVar[str] = "generic"
    SUPPORTED_FORMATS: ClassVar[list[str]] = ["csv", "tsv", "xls", "xlsx", "pdf"]

    @classmethod
    def detect(cls, file_path: str | Path, content_sample: str) -> float:
        """Low, never-winning score reflecting how table-like the file looks.

        Capped at 0.45 so a named parser (≥0.50) always wins. A spreadsheet's or
        PDF's content isn't in `content_sample`, so those get a flat low base.
        """
        ext = Path(file_path).suffix.lower()
        if ext == ".pdf":
            return 0.12  # last-resort lane for any PDF a named parser didn't claim
        if ext not in _TABULAR_EXT:
            return 0.0
        if ext in (".xls", ".xlsx", ".xlsm"):
            return 0.15
        return _text_table_likeness(content_sample)

    def parse(self, file_path: str | Path) -> list[Transaction]:
        # Late imports break the parsers ↔ import_engine load-time cycle.
        from backend.import_engine.classify_columns import classify_columns
        from backend.import_engine.classify_tx import RowState, classify_table
        from backend.import_engine.diagnostics import build_diagnostics, set_last_diagnostics
        from backend.import_engine.table_extract import extract

        path = Path(file_path)
        set_last_diagnostics(None)
        if path.suffix.lower() not in _TABULAR_EXT:
            logger.warning("Generic engine cannot handle %s files", path.suffix)
            return []

        try:
            et = extract(path)
        except Exception as e:
            logger.warning("Generic engine could not read %s: %s", path, e)
            return []
        if not et.header or not et.rows:
            logger.info("Generic engine: no usable table found in %s", path.name)
            return []

        mapping = classify_columns(et)
        classified = classify_table(et.rows, mapping)

        institution = _detect_institution(path) or _GENERIC_LABEL
        account_prefix = _account_prefix(path)

        fx = get_fx_service()
        txs: list[Transaction] = []
        for cr in classified:
            if cr.state not in (RowState.CONFIDENT, RowState.WITH_ASSUMPTIONS):
                continue  # PARTIAL / UNMAPPED — kept in diagnostics, never persisted
            t = _build_transaction(cr, account_prefix, institution, path.name)
            if t is None:
                continue
            fx.populate_transaction(t)
            txs.append(t)

        diag = build_diagnostics(
            et, mapping, classified, institution=institution, persisted_rows=len(txs)
        )
        set_last_diagnostics(diag)
        logger.info(
            "Generic engine parsed %s: %d data rows, %d persistable, states=%s, institution=%r",
            path.name, len(classified), len(txs), diag.state_counts, institution,
        )
        return txs


# --------------------------------------------------------------------------- #
# detect() heuristic                                                          #
# --------------------------------------------------------------------------- #

def _text_table_likeness(sample: str) -> float:
    """0.10–0.45 score for how much a text sample resembles a delimited table."""
    if not sample or not sample.strip():
        return 0.10
    lines = [ln for ln in sample.splitlines() if ln.strip()]
    if len(lines) < 2:
        return 0.10
    delim = sniff_csv_delimiter(sample)
    counts = [ln.count(delim) + 1 for ln in lines[:12]]
    multi = [c for c in counts if c >= 2]
    if not multi:
        return 0.10
    common = max(set(multi), key=multi.count)
    consistent = sum(1 for c in counts if c == common) / len(counts)
    score = 0.20 + 0.20 * consistent  # 0.20–0.40
    if common >= 4:
        score += 0.05
    return round(min(score, 0.45), 3)


# --------------------------------------------------------------------------- #
# Institution / account detection from the preamble                           #
# --------------------------------------------------------------------------- #

def _detect_institution(path: Path) -> str | None:
    """Best-effort institution name from the file's preamble/header text."""
    sample = read_text_sample(path, max_bytes=2048)
    if not sample:
        return None
    low = sample.lower()
    for kw in _INSTITUTION_KEYWORDS:
        if kw in low:
            return kw.title()
    # Fall back to the first preamble title line (not an account/meta/data line).
    for line in sample.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.count(",") >= 2:
            break  # reached the data/header grid — stop looking
        if re.match(r"^(account|generated|period|date|statement period)\b", s, re.I):
            continue
        title = re.split(r"\s+[—–-]\s+", s)[0].strip()
        title = re.sub(
            r"\b(transaction export|activities?|statement|export|report)\b.*$",
            "", title, flags=re.I,
        ).strip(" ,—–-")
        if 2 <= len(title) <= 60:
            return title
    return None


def _account_prefix(path: Path) -> str:
    """Stable account-number prefix for hashing, from a preamble 'Account:' line."""
    sample = read_text_sample(path, max_bytes=2048)
    m = re.search(r"account[:#]?\s*([\w-]+)", sample, re.I)
    return m.group(1) if m else "generic"


# --------------------------------------------------------------------------- #
# ClassifiedRow → Transaction                                                  #
# --------------------------------------------------------------------------- #

def _build_transaction(cr, account_prefix: str, institution: str, source_file: str) -> Transaction | None:
    """Emit a persistable Transaction from a CONFIDENT/WITH_ASSUMPTIONS row."""
    nr = cr.normalized
    trade_date = nr.values.get(F.TRANSACTION_DATE)
    if trade_date is None:  # defensive — required-field gate should preclude this
        return None

    account_type = nr.values.get(F.ACCOUNT_TYPE, "Non-Registered")
    account_number = f"{account_prefix}-{account_type}"
    raw_symbol = nr.values.get(F.TICKER)
    currency = nr.values.get(F.CURRENCY, "CAD")
    quantity = float(nr.values.get(F.QUANTITY, 0.0) or 0.0)
    net = float(nr.values.get(F.NET_AMOUNT, 0.0) or 0.0)

    h = compute_hash(
        transaction_date=trade_date,
        action=cr.emitted_action,
        raw_symbol=raw_symbol,
        quantity=quantity,
        net_amount=net,
        account_number=account_number,
    )
    note = (
        "Imported via generic engine"
        if institution == _GENERIC_LABEL
        else f"Imported via generic engine from {institution}"
    )
    return Transaction(
        hash=h,
        broker="generic",
        transaction_date=trade_date,
        settlement_date=nr.values.get(F.SETTLEMENT_DATE),
        action=cr.emitted_action,
        raw_symbol=raw_symbol,
        description=nr.values.get(F.SECURITY_NAME, "") or "",
        quantity=quantity,
        price=float(nr.values.get(F.PRICE, 0.0) or 0.0),
        gross_amount=float(nr.values.get(F.GROSS_AMOUNT, 0.0) or 0.0),
        commission=float(nr.values.get(F.COMMISSION, 0.0) or 0.0),
        net_amount=net,
        currency=currency,
        account_number=account_number,
        account_type=account_type,
        isin=nr.values.get(F.ISIN),
        exchange=nr.values.get(F.EXCHANGE) or guess_exchange(raw_symbol, currency),
        reference_id=nr.values.get(F.REFERENCE_ID),
        notes=note,
        source_file=source_file,
    )
