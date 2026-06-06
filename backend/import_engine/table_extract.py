"""Find-the-table + find-the-header-row for the universal import lane
(Item 4, Step 2).

A raw grid from `readers.py` may carry preamble/title lines, blank rows, merged
title cells, repeated header rows mid-file, and subtotal/footer rows. This module
locates the real transaction table and its header row, then returns a clean
ExtractedTable (header labels + aligned data rows) for the column classifier
(Step 3) to map.

Header detection is deterministic and alias-driven: score each candidate row by
how many of its cells resolve to a `CanonicalField` via the bilingual alias
dictionary (`aliases.match_label`). The best-scoring row in the first N rows is
the header; everything above it is preamble. A row identical to the header later
in the file is a repeated header (suppressed); obvious subtotal/footer/disclaimer
rows are dropped.

No fuzzy matching or value-profiling yet — those join in Step 3 to rescue files
whose headers don't hit an exact alias.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.import_engine.aliases import match_label, normalize_label
from backend.import_engine.canonical import CanonicalField
from backend.import_engine.readers import RawTable, read_tabular

# How many leading rows to consider as potential header rows.
HEADER_SCAN_ROWS = 25

# Sheet-name hints that mark a worksheet as the likely transaction table.
_SHEET_NAME_HINTS = (
    "activit", "transaction", "trade", "history", "activity", "orders", "ledger",
)

# Footer/subtotal/disclaimer markers (matched on a row's first non-empty cell).
_FOOTER_RE = re.compile(
    r"^(sub[\s-]*total|total|grand total|opening balance|closing balance|"
    r"balance|disclaimer|generated|page\s+\d|end of report|summary)\b",
    re.I,
)


@dataclass
class ExtractedTable:
    """A located transaction table with its header row identified."""

    header: list[str]
    header_row_index: int
    rows: list[list[str]]
    fmt: str
    sheet_name: str | None = None
    matched_fields: dict[int, CanonicalField] = field(default_factory=dict)
    header_score: int = 0
    n_preamble_skipped: int = 0
    n_footer_dropped: int = 0
    n_repeated_headers_suppressed: int = 0
    n_blank_dropped: int = 0

    @property
    def n_data_rows(self) -> int:
        return len(self.rows)


# --------------------------------------------------------------------------- #
# Header-row scoring                                                           #
# --------------------------------------------------------------------------- #

def _non_empty(cells: list[str]) -> int:
    return sum(1 for c in cells if c and c.strip())


def header_alias_hits(cells: list[str]) -> dict[int, CanonicalField]:
    """Map each cell that resolves to a canonical field → {col_index: field}.

    Distinct-field counting (a row of three columns all aliasing to net_amount is
    weaker than three columns aliasing to three different fields), so a duplicate
    field on a later column doesn't inflate the score.
    """
    seen: dict[CanonicalField, int] = {}
    hits: dict[int, CanonicalField] = {}
    for i, cell in enumerate(cells):
        fld = match_label(cell)
        if fld is not None and fld not in seen:
            seen[fld] = i
            hits[i] = fld
    return hits


def score_header_row(cells: list[str]) -> tuple[int, int]:
    """Score a candidate header row → (distinct alias hits, non-empty cells)."""
    return len(header_alias_hits(cells)), _non_empty(cells)


def find_header_row(rows: list[list[str]], scan: int = HEADER_SCAN_ROWS) -> int:
    """Index of the most header-like row among the first `scan` rows.

    Picks the row with the most distinct alias hits; ties break toward more
    non-empty cells, then the earliest row. If NO row hits an alias (a truly
    header-less file), falls back to the first row with >= 2 non-empty cells so
    Step 3 value-profiling has something to work with.
    """
    best_idx = -1
    best_key = (-1, -1)  # (alias_hits, non_empty)
    limit = min(scan, len(rows))
    for i in range(limit):
        hits, non_empty = score_header_row(rows[i])
        key = (hits, non_empty)
        if key > best_key:
            best_key = key
            best_idx = i
    if best_idx >= 0 and best_key[0] > 0:
        return best_idx
    # Headerless fallback: first row with >= 2 non-empty cells, else row 0.
    for i in range(len(rows)):
        if _non_empty(rows[i]) >= 2:
            return i
    return 0


# --------------------------------------------------------------------------- #
# Row cleanup                                                                  #
# --------------------------------------------------------------------------- #

def _is_footer_row(cells: list[str]) -> bool:
    """True for subtotal/total/disclaimer/footer rows (conservative)."""
    non_empty = [c for c in cells if c and c.strip()]
    if not non_empty:
        return False
    first = non_empty[0].strip()
    if _FOOTER_RE.match(first):
        return True
    # A lone "Total ..." style cell sitting in a mostly-empty row is a footer.
    if len(non_empty) <= 2 and any(_FOOTER_RE.match(c.strip()) for c in non_empty):
        return True
    return False


def _same_as_header(cells: list[str], header_norm: list[str]) -> bool:
    """True if a row is a repeat of the header (normalized cell-by-cell)."""
    norm = [normalize_label(c) for c in cells]
    # Compare on the header's width; trailing extra empties are ignored.
    width = len(header_norm)
    return norm[:width] == header_norm and any(header_norm)


# --------------------------------------------------------------------------- #
# Sheet selection (multi-sheet Excel)                                          #
# --------------------------------------------------------------------------- #

def _sheet_name_bonus(name: str | None) -> int:
    if not name:
        return 0
    low = name.lower()
    return 2 if any(h in low for h in _SHEET_NAME_HINTS) else 0


def pick_best_sheet(tables: list[RawTable]) -> RawTable:
    """Choose the worksheet most likely to hold the transaction table.

    Scores each sheet by its best header-row alias hits + a name-hint bonus +
    a small density term, so a 'Summary'/'Pivot' sheet loses to 'Activities'.
    """
    if len(tables) == 1:
        return tables[0]
    best = tables[0]
    best_score = -1.0
    for t in tables:
        if not t.rows:
            continue
        h = find_header_row(t.rows)
        hits, _ = score_header_row(t.rows[h]) if h < len(t.rows) else (0, 0)
        density = min(len(t.rows), 50) / 50.0  # prefer sheets with real data
        score = hits * 10 + _sheet_name_bonus(t.sheet_name) + density
        if score > best_score:
            best_score = score
            best = t
    return best


# --------------------------------------------------------------------------- #
# Top-level extraction                                                         #
# --------------------------------------------------------------------------- #

def extract_from_grid(rows: list[list[str]], fmt: str, sheet_name: str | None = None) -> ExtractedTable:
    """Locate the header row in a raw grid and return the cleaned table."""
    if not rows:
        return ExtractedTable(header=[], header_row_index=-1, rows=[], fmt=fmt, sheet_name=sheet_name)

    h = find_header_row(rows)
    header = rows[h]
    header_norm = [normalize_label(c) for c in header]
    matched = header_alias_hits(header)
    width = len(header)

    data: list[list[str]] = []
    n_footer = n_repeat = n_blank = 0
    for r in rows[h + 1:]:
        if _non_empty(r) == 0:
            n_blank += 1
            continue
        if _same_as_header(r, header_norm):
            n_repeat += 1
            continue
        if _is_footer_row(r):
            n_footer += 1
            continue
        # Align to header width (pad short rows, keep overflow for diagnostics).
        row = list(r)
        if len(row) < width:
            row = row + [""] * (width - len(row))
        data.append(row)

    return ExtractedTable(
        header=header,
        header_row_index=h,
        rows=data,
        fmt=fmt,
        sheet_name=sheet_name,
        matched_fields=matched,
        header_score=len(matched),
        n_preamble_skipped=h,
        n_footer_dropped=n_footer,
        n_repeated_headers_suppressed=n_repeat,
        n_blank_dropped=n_blank,
    )


def extract(path) -> ExtractedTable:
    """Read a file, pick the best sheet, and extract its transaction table."""
    tables = read_tabular(path)
    best = pick_best_sheet(tables)
    return extract_from_grid(best.rows, fmt=best.fmt, sheet_name=best.sheet_name)
