"""Column classifier for the universal import lane (Item 4, Step 3).

Takes an `ExtractedTable` (Step 2) and decides which source column maps to which
`CanonicalField`, with a confidence per field and an overall mapping confidence.

Three passes, highest-confidence-first:

  1. EXACT ALIAS  — `aliases.match_label(header)` (already computed during
     extraction). Confidence 1.0. Deterministic.
  2. FUZZY        — `rapidfuzz.fuzz.token_set_ratio` of the header text against
     every alias of each not-yet-claimed field, above FUZZY_THRESHOLD. Confidence
     scales 0.60–0.85 with the score. If the column's VALUES also profile to the
     same field, the guess is confirmed with a small boost.
  3. VALUE PROFILE — independent of header text: profile each column's first N
     data values for date-/amount-/quantity-/ticker-/ISIN-/currency-/enum-like
     shape. Confidence 0.40–0.60. Resolves header-less or garbled columns.

Assignment is greedy by confidence with a strict one-field-per-column AND
one-column-per-field invariant: when two fields want the same column (or one
field matches two columns), the higher-confidence pairing wins.

Finally the mapping is checked against `canonical.FILE_LEVEL_RULE` so callers
(Steps 4 and 7) get `missing_required` — the columns whose absence blocks the
import.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from backend.import_engine.aliases import CANONICAL_ALIASES, match_label, normalize_label
from backend.import_engine.canonical import (
    FILE_LEVEL_RULE,
    CanonicalField,
    requirement_gaps,
)
from backend.import_engine.table_extract import ExtractedTable
from backend.parsers._common import _CURRENCY_CODES, normalize_action, parse_date, safe_float

# --- tunable thresholds (named constants so they're adjustable in one place) ---
FUZZY_THRESHOLD = 80           # rapidfuzz token_set_ratio cutoff for a fuzzy hit
PROFILE_SAMPLE = 25            # how many data values to profile per column
PROFILE_MIN_FRACTION = 0.70    # fraction of values that must fit a shape
ALIAS_CONFIDENCE = 1.0
PROFILE_CONFIRM_BOOST = 0.10   # added when value-profiling confirms a fuzzy guess

_F = CanonicalField


@dataclass
class MappingResult:
    """The classifier's verdict for one file."""

    mapping: dict[CanonicalField, int] = field(default_factory=dict)
    field_confidence: dict[CanonicalField, float] = field(default_factory=dict)
    method_by_field: dict[CanonicalField, str] = field(default_factory=dict)  # alias|fuzzy|profile
    overall_confidence: float = 0.0
    missing_required: list[str] = field(default_factory=list)
    unmapped_columns: list[int] = field(default_factory=list)
    header: list[str] = field(default_factory=list)

    def column_for(self, f: CanonicalField) -> int | None:
        return self.mapping.get(f)


# --------------------------------------------------------------------------- #
# Value profiling                                                             #
# --------------------------------------------------------------------------- #

_TICKER_RE = re.compile(r"^[A-Z]{1,6}([.\-][A-Z0-9]{1,4})?$")
_ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
_MONEYISH_RE = re.compile(r"[$£€¥]|\(.*\)|,\d{3}|\.\d{2}\b|-")


def _fraction(predicate, values: list[str]) -> float:
    if not values:
        return 0.0
    return sum(1 for v in values if predicate(v)) / len(values)


def _is_numeric(v: str) -> bool:
    s = v.strip()
    if not s or s in {"-", "—"}:
        return False
    # safe_float returns 0.0 both for "0" and for junk, so guard junk explicitly.
    cleaned = re.sub(r"[^0-9.\-]", "", s.replace("(", "-").replace(")", ""))
    if cleaned in {"", "-", ".", "-."}:
        return False
    try:
        float(cleaned)
        return True
    except ValueError:
        return False


def _looks_smallint(v: str) -> bool:
    try:
        f = float(re.sub(r"[^0-9.\-]", "", v.strip()))
    except ValueError:
        return False
    return abs(f) < 1_000_000 and "$" not in v and abs(f - round(f)) < 1e-9


def profile_column(values: list[str]) -> dict[CanonicalField, float]:
    """Profile a column's values → {candidate field: profile confidence 0–1}."""
    vals = [v.strip() for v in values if v and v.strip()][:PROFILE_SAMPLE]
    if not vals:
        return {}
    scores: dict[CanonicalField, float] = {}

    date_frac = _fraction(lambda v: parse_date(v) is not None, vals)
    if date_frac >= PROFILE_MIN_FRACTION:
        scores[_F.TRANSACTION_DATE] = round(0.45 + 0.15 * date_frac, 3)

    isin_frac = _fraction(lambda v: bool(_ISIN_RE.match(v.upper())), vals)
    if isin_frac >= PROFILE_MIN_FRACTION:
        scores[_F.ISIN] = round(0.50 + 0.10 * isin_frac, 3)

    cur_frac = _fraction(lambda v: v.upper() in _CURRENCY_CODES, vals)
    if cur_frac >= PROFILE_MIN_FRACTION:
        scores[_F.CURRENCY] = round(0.50 + 0.10 * cur_frac, 3)

    tick_frac = _fraction(
        lambda v: bool(_TICKER_RE.match(v)) and v.upper() not in _CURRENCY_CODES, vals
    )
    if tick_frac >= 0.60 and _F.CURRENCY not in scores:
        scores[_F.TICKER] = round(0.40 + 0.15 * tick_frac, 3)

    distinct = len({v.lower() for v in vals})
    act_frac = _fraction(lambda v: normalize_action(v) != "OTHER", vals)
    if act_frac >= PROFILE_MIN_FRACTION and distinct <= max(6, len(vals) // 2):
        scores[_F.ACTION] = round(0.40 + 0.15 * act_frac, 3)

    num_frac = _fraction(_is_numeric, vals)
    if num_frac >= PROFILE_MIN_FRACTION and _F.TRANSACTION_DATE not in scores:
        money_frac = _fraction(lambda v: bool(_MONEYISH_RE.search(v)), vals)
        int_frac = _fraction(_looks_smallint, vals)
        if money_frac >= 0.40:
            scores[_F.NET_AMOUNT] = 0.50
        elif int_frac >= 0.60:
            scores[_F.QUANTITY] = 0.45
        else:
            scores[_F.NET_AMOUNT] = 0.40
    return scores


# --------------------------------------------------------------------------- #
# Fuzzy header matching                                                       #
# --------------------------------------------------------------------------- #

def _best_fuzzy_field(header_cell: str) -> tuple[CanonicalField | None, float]:
    """Best fuzzy (field, token_set_ratio) for a header cell across all aliases."""
    norm = normalize_label(header_cell)
    if not norm:
        return None, 0.0
    best_field: CanonicalField | None = None
    best_score = 0.0
    for fld, labels in CANONICAL_ALIASES.items():
        for label in labels:
            score = fuzz.token_set_ratio(norm, normalize_label(label))
            if score > best_score:
                best_score = score
                best_field = fld
    return best_field, best_score


# --------------------------------------------------------------------------- #
# Classification                                                              #
# --------------------------------------------------------------------------- #

@dataclass
class _Candidate:
    field: CanonicalField
    col: int
    confidence: float
    method: str


def _column_values(et: ExtractedTable, col: int) -> list[str]:
    return [row[col] for row in et.rows if col < len(row)]


_CORE_FIELDS = (
    _F.TRANSACTION_DATE,
    _F.ACTION,
    _F.TICKER,
    _F.QUANTITY,
    _F.PRICE,
    _F.NET_AMOUNT,
    _F.CURRENCY,
)


def classify_columns(et: ExtractedTable) -> MappingResult:
    """Map an ExtractedTable's columns to canonical fields with confidence."""
    width = len(et.header)
    candidates: list[_Candidate] = []

    # Pass 1 — exact alias (precomputed in extraction; recompute defensively).
    alias_cols: dict[int, CanonicalField] = dict(et.matched_fields) or {
        i: f for i in range(width) if (f := match_label(et.header[i])) is not None
    }
    for col, fld in alias_cols.items():
        candidates.append(_Candidate(fld, col, ALIAS_CONFIDENCE, "alias"))

    # Profile every column once (reused by passes 2 and 3).
    col_profiles: dict[int, dict[CanonicalField, float]] = {
        col: profile_column(_column_values(et, col)) for col in range(width)
    }

    # Pass 2 — fuzzy on columns without an exact alias hit.
    for col in range(width):
        if col in alias_cols:
            continue
        fld, score = _best_fuzzy_field(et.header[col])
        if fld is None or score < FUZZY_THRESHOLD:
            continue
        conf = 0.60 + 0.25 * (min(score, 100.0) - FUZZY_THRESHOLD) / (100.0 - FUZZY_THRESHOLD)
        if fld in col_profiles.get(col, {}):  # value-profiling confirms the guess
            conf = min(0.95, conf + PROFILE_CONFIRM_BOOST)
        candidates.append(_Candidate(fld, col, round(conf, 3), "fuzzy"))

    # Pass 3 — value profiling for columns still without alias/fuzzy.
    for col in range(width):
        if col in alias_cols:
            continue
        for fld, pconf in col_profiles.get(col, {}).items():
            candidates.append(_Candidate(fld, col, pconf, "profile"))

    # Greedy resolve: highest confidence first, strict 1:1 field↔column.
    method_rank = {"alias": 3, "fuzzy": 2, "profile": 1}
    candidates.sort(key=lambda c: (c.confidence, method_rank[c.method]), reverse=True)

    mapping: dict[CanonicalField, int] = {}
    field_conf: dict[CanonicalField, float] = {}
    method_by: dict[CanonicalField, str] = {}
    used_cols: set[int] = set()
    for c in candidates:
        if c.field in mapping or c.col in used_cols:
            continue
        mapping[c.field] = c.col
        field_conf[c.field] = c.confidence
        method_by[c.field] = c.method
        used_cols.add(c.col)

    unmapped_cols = [i for i in range(width) if i not in used_cols]
    missing = requirement_gaps(set(mapping), FILE_LEVEL_RULE)

    # Overall confidence: mean field confidence scaled by core-field coverage.
    if field_conf:
        mean_conf = sum(field_conf.values()) / len(field_conf)
        core_cov = sum(1 for f in _CORE_FIELDS if f in mapping) / len(_CORE_FIELDS)
        overall = round(mean_conf * (0.5 + 0.5 * core_cov), 3)
    else:
        overall = 0.0

    return MappingResult(
        mapping=mapping,
        field_confidence=field_conf,
        method_by_field=method_by,
        overall_confidence=overall,
        missing_required=missing,
        unmapped_columns=unmapped_cols,
        header=list(et.header),
    )
