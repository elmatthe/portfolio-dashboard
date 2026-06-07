"""Per-row transaction classifier for the universal import lane (Item 4, Step 4).

Consumes a `NormalizedRow` (from `normalize.py`) plus the Step-3 `MappingResult`
and decides:

  * `canonical_action` — the RICH `CanonicalAction` label (16-value taxonomy) used
    purely for diagnostics / traceability.
  * `emitted_action`   — that label mapped DOWN through `ACTION_DOWNMAP` to one of
    the 11 stored `backend.models.Action` values. The ONLY action that reaches the
    DB / ACB / reports.
  * `state` — one of the four §4 outcomes:
        CONFIDENT        every required field present, action certain.
        WITH_ASSUMPTIONS imported, but ≥1 field was inferred/derived (or the action
                         was inferred from row shape rather than an explicit label).
        PARTIAL          recoverable: a required field is missing; the diagnostics
                         name which field and which downstream calc it blocks.
        UNMAPPED         cannot be classified at all — KEPT, never dropped.
  * `confidence` — a 0–1 row score.
  * `diagnostics` — human-readable lines for Step 5's `ImportDiagnostics`.

Action determination reuses `backend.parsers._common.normalize_action` for shape
inference (sign + quantity + symbol presence); a richer keyword table promotes the
shape result to the full canonical taxonomy (DRIP, return-of-capital, journal, …).
Field-gap evaluation reuses `canonical.requirement_gaps` against the per-action
`MIN_SCHEMA` rule built in Step 1.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from backend.import_engine.canonical import (
    MIN_SCHEMA,
    CanonicalAction,
    CanonicalField,
    requirement_gaps,
    to_emitted_action,
)
from backend.import_engine.classify_columns import MappingResult
from backend.import_engine.normalize import NormalizedRow
from backend.parsers._common import normalize_action

_F = CanonicalField
_A = CanonicalAction

# Action confidence at/above which an EXPLICIT label is trusted without forcing a
# row to WITH_ASSUMPTIONS purely on action grounds.
ACTION_CONFIDENT_THRESHOLD = 0.75


class RowState(str, Enum):
    CONFIDENT = "confident"
    WITH_ASSUMPTIONS = "with_assumptions"
    PARTIAL = "partial"
    UNMAPPED = "unmapped"


# Raw-label keyword → rich CanonicalAction. Checked as ordered substrings so
# "Cash Dividend Receipt" → DIVIDEND, "DRIP - Reinvestment" → REINVEST_DRIP, etc.
# More specific phrases MUST precede the generic ones they contain.
_CANONICAL_VOCAB: tuple[tuple[str, CanonicalAction], ...] = (
    ("drip", _A.REINVEST_DRIP),
    ("reinvest", _A.REINVEST_DRIP),
    ("return of capital", _A.RETURN_OF_CAPITAL),
    ("roc", _A.RETURN_OF_CAPITAL),
    ("withholding", _A.TAX_WITHHOLDING),
    ("non-resident tax", _A.TAX_WITHHOLDING),
    ("nr tax", _A.TAX_WITHHOLDING),
    ("journal", _A.JOURNAL),
    ("merger", _A.CORPORATE_ACTION),
    ("spinoff", _A.CORPORATE_ACTION),
    ("spin-off", _A.CORPORATE_ACTION),
    ("corporate action", _A.CORPORATE_ACTION),
    ("name change", _A.CORPORATE_ACTION),
    ("split", _A.SPLIT),
    ("contribution", _A.CONTRIBUTION),
    ("transfer in", _A.TRANSFER_IN),
    ("transfer out", _A.TRANSFER_OUT),
    ("deposit", _A.TRANSFER_IN),
    ("withdrawal", _A.WITHDRAWAL),
    ("dividend", _A.DIVIDEND),
    ("distribution", _A.DIVIDEND),
    ("interest", _A.INTEREST),
    ("commission", _A.FEE),
    ("fee", _A.FEE),
    ("bought", _A.BUY),
    ("buy", _A.BUY),
    ("purchase", _A.BUY),
    ("sold", _A.SELL),
    ("sell", _A.SELL),
    ("redem", _A.SELL),
)

# Map the 11 emitted actions (from shape inference) back to a representative rich
# CanonicalAction for MIN_SCHEMA lookup when no label keyword matched.
_EMITTED_TO_CANONICAL: dict[str, CanonicalAction] = {
    "BUY": _A.BUY,
    "SELL": _A.SELL,
    "DIVIDEND": _A.DIVIDEND,
    "DEPOSIT": _A.TRANSFER_IN,
    "WITHDRAWAL": _A.WITHDRAWAL,
    "CONTRIBUTION": _A.CONTRIBUTION,
    "FEE": _A.FEE,
    "SPLIT": _A.SPLIT,
    "INTEREST": _A.INTEREST,
    "TRANSFER": _A.JOURNAL,
    "OTHER": _A.CASH_ADJUSTMENT,
}

# Gap token (from requirement_gaps) → the downstream calculation it blocks. Tokens
# can be a bare field value ("net_amount"), an any_of group ("a|b"), or an n_of
# group ("2_of:a|b|c"); we match on the field names they contain.
_BLOCKS = {
    "transaction_date": "period return (Modified-Dietz), ACB lot ordering, FX rate lookup",
    "net_amount": "period return (cash-flow), FX conversion (net_cad)",
    "quantity": "ACB / cost basis and capital gains",
    "price": "ACB / cost basis and capital gains",
    "ticker": "per-security ACB grouping and capital gains",
    "security_name": "per-security ACB grouping and capital gains",
    "currency": "FX conversion (net_cad)",
}


@dataclass
class ClassifiedRow:
    """A normalized row with its action, outcome state, and diagnostics."""

    normalized: NormalizedRow
    canonical_action: CanonicalAction
    emitted_action: str
    state: RowState
    confidence: float
    action_inferred: bool
    missing_fields: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)

    @property
    def dropped(self) -> bool:
        """Rows are NEVER dropped — even UNMAPPED ones are retained for review."""
        return False


# --------------------------------------------------------------------------- #
# Action inference                                                             #
# --------------------------------------------------------------------------- #

def infer_action(norm: NormalizedRow) -> tuple[CanonicalAction, float, bool]:
    """Determine (canonical_action, confidence, inferred?) for a normalized row.

    An explicit label that matches the keyword table is trusted (confidence 0.9,
    inferred=False). Otherwise the action is inferred from row shape via
    `normalize_action` (confidence 0.6, inferred=True). A row with no usable signal
    falls back to CASH_ADJUSTMENT at low confidence.
    """
    raw_action = str(norm.values.get(_F.ACTION, "") or "").lower()
    if raw_action:
        for needle, action in _CANONICAL_VOCAB:
            if needle in raw_action:
                return action, 0.9, False

    # Shape inference: reuse the broker-parser vocabulary/heuristics.
    abs_qty = float(norm.values.get(_F.QUANTITY, 0.0) or 0.0)
    net = float(norm.values.get(_F.NET_AMOUNT, 0.0) or 0.0)
    emitted = normalize_action(raw_action or None, quantity=abs_qty, net=net)
    canonical = _EMITTED_TO_CANONICAL.get(emitted, _A.CASH_ADJUSTMENT)

    has_signal = bool(abs_qty) or bool(net) or _F.TICKER in norm.values
    if canonical is _A.CASH_ADJUSTMENT and not has_signal:
        return _A.CASH_ADJUSTMENT, 0.2, True
    return canonical, 0.6, True


# --------------------------------------------------------------------------- #
# Outcome state                                                               #
# --------------------------------------------------------------------------- #

def _blocking_calc(gap_token: str) -> str:
    """Which downstream calc a missing-field gap token blocks."""
    blocked = [calc for fieldname, calc in _BLOCKS.items() if fieldname in gap_token]
    return "; ".join(dict.fromkeys(blocked)) if blocked else "import completeness"


def _has_anchor(norm: NormalizedRow) -> bool:
    """A row is anchorable if it has a date AND at least one transactional value."""
    has_date = _F.TRANSACTION_DATE in norm.values
    has_value = any(
        f in norm.values for f in (_F.NET_AMOUNT, _F.QUANTITY, _F.GROSS_AMOUNT, _F.TICKER)
    )
    return has_date and has_value


def classify_row(norm: NormalizedRow, mapping: MappingResult | None = None) -> ClassifiedRow:
    """Classify a single normalized row into one of the four outcome states."""
    canonical, action_conf, inferred = infer_action(norm)
    emitted = to_emitted_action(canonical)  # guaranteed one of the stored 11

    rule = MIN_SCHEMA[canonical]
    gaps = requirement_gaps(norm.mapped_fields, rule)

    diagnostics: list[str] = []
    for g in gaps:
        diagnostics.append(f"missing {g} → blocks {_blocking_calc(g)}")

    # Decide the outcome state.
    if gaps:
        if _has_anchor(norm):
            state = RowState.PARTIAL
        else:
            state = RowState.UNMAPPED
            diagnostics.append("no usable date + value anchor — kept for manual review")
    elif norm.has_derivations or inferred:
        state = RowState.WITH_ASSUMPTIONS
        for line in norm.derivations:
            diagnostics.append(f"assumption: {line}")
        for line in norm.assumptions:
            diagnostics.append(f"assumption: {line}")
        if inferred:
            diagnostics.append(
                f"assumption: action inferred as {canonical.value} from row shape"
            )
    else:
        state = RowState.CONFIDENT

    # Confidence: start from the action confidence, penalise assumptions and gaps.
    conf = action_conf
    conf -= 0.10 * (len(norm.derivations) + len(norm.assumptions))
    conf -= 0.25 * len(gaps)
    if state is RowState.UNMAPPED:
        conf = min(conf, 0.2)
    conf = max(0.05, min(1.0, round(conf, 3)))

    return ClassifiedRow(
        normalized=norm,
        canonical_action=canonical,
        emitted_action=emitted,
        state=state,
        confidence=conf,
        action_inferred=inferred,
        missing_fields=gaps,
        diagnostics=diagnostics,
    )


def classify_table(rows, mapping: MappingResult):
    """Normalize + classify every row of an extracted table. Convenience for Step 5.

    `rows` is an iterable of raw cell-string lists (`ExtractedTable.rows`).
    """
    from backend.import_engine.normalize import normalize_row

    out: list[ClassifiedRow] = []
    for row in rows:
        out.append(classify_row(normalize_row(row, mapping), mapping))
    return out
