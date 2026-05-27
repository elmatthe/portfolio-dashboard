"""Pre-insert validation for imported transactions.

Runs AFTER parsing, BEFORE store.upsert_transactions. Rejects/skips rows
whose dates are unparseable or whose required numeric fields are non-numeric,
so corrupted data can never enter the DB and later 500 the portfolio endpoint.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime

from backend.models import Transaction

log = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    valid: list[Transaction] = field(default_factory=list)
    skipped: int = 0
    warnings: list[str] = field(default_factory=list)


def validate_transactions(txs: list[Transaction]) -> ValidationResult:
    """Filter a parsed transaction list, keeping only rows safe to persist."""
    result = ValidationResult()
    for i, t in enumerate(txs, start=1):
        issues: list[str] = []

        if not _is_valid_date(t.transaction_date):
            issues.append(f"row {i}: invalid transaction_date ({t.transaction_date!r})")

        if not _is_finite_number(t.quantity):
            issues.append(f"row {i}: non-numeric quantity ({t.quantity!r})")

        if not _is_finite_number(t.price):
            issues.append(f"row {i}: non-numeric price ({t.price!r})")

        if not _is_finite_number(t.net_amount):
            issues.append(f"row {i}: non-numeric net_amount ({t.net_amount!r})")

        if issues:
            result.skipped += 1
            result.warnings.extend(issues)
            log.warning("Skipping invalid row %d: %s", i, "; ".join(issues))
        else:
            result.valid.append(t)

    if result.skipped:
        result.warnings.insert(
            0,
            f"Imported {len(result.valid)} of {len(txs)} rows. "
            f"{result.skipped} rows skipped due to invalid data.",
        )

    return result


def _is_valid_date(d) -> bool:
    """True if d is a proper Python date (not None, not NaT-like)."""
    if d is None:
        return False
    if isinstance(d, (date, datetime)):
        return True
    try:
        date.fromisoformat(str(d))
        return True
    except (ValueError, TypeError):
        return False


def _is_finite_number(v) -> bool:
    """True if v is a finite number (int or float, not NaN/Inf)."""
    if v is None:
        return False
    try:
        f = float(v)
        import math
        return math.isfinite(f)
    except (ValueError, TypeError):
        return False
