"""Import diagnostics for the universal import lane (Item 4, Step 5).

`ImportDiagnostics` is the structured answer to the four plan questions the
generic importer must always be able to answer about a file it ingested:

  1. What was confidently identified — per-state row counts, the detected
     institution, the header row index, and the field→column map with a
     per-field confidence + overall mapping confidence.
  2. What was inferred — the per-row assumptions/derivations the normalizer and
     classifier applied (sign flips, qty×price derivations, inferred actions, …).
  3. What is missing — per-row absent required fields and which downstream
     calculation (ACB, capital gains, period return, FX) each one blocks.
  4. The minimum correction — the smallest set of column re-assignments that
     would move PARTIAL/UNMAPPED rows into a mappable state. This is what the
     Step 7 column-mapping editor consumes to pre-fill its suggestions.

`ImportResult` wraps the persisted `Transaction`s alongside the diagnostics and a
`skipped_rows` count, mirroring the shape Item 0 validation already returns so the
import endpoint can treat the generic lane and the named lane uniformly.

Pure data: no I/O, no FastAPI, no DB. The only state is a tiny module-level stash
(`set_last_diagnostics` / `pop_last_diagnostics`) so the generic parser — which
the registry invokes through the fixed `parse() -> list[Transaction]` contract —
can hand its diagnostics back to the endpoint without changing that contract.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from backend.import_engine.classify_tx import RowState

if TYPE_CHECKING:  # avoid runtime import cycles / heavy deps in this pure module
    from backend.import_engine.classify_columns import MappingResult
    from backend.import_engine.classify_tx import ClassifiedRow
    from backend.import_engine.table_extract import ExtractedTable
    from backend.models import Transaction


# --------------------------------------------------------------------------- #
# Diagnostics                                                                 #
# --------------------------------------------------------------------------- #

@dataclass
class FieldMapEntry:
    """One canonical field → source column, with how it was matched."""

    field: str
    column_index: int
    column_name: str
    confidence: float
    method: str  # alias | fuzzy | profile

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "column_index": self.column_index,
            "column_name": self.column_name,
            "confidence": round(self.confidence, 3),
            "method": self.method,
        }


@dataclass
class RowNote:
    """Per-row inference / gap record (questions 2 and 3)."""

    row_index: int
    state: str
    assumptions: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_index": self.row_index,
            "state": self.state,
            "assumptions": self.assumptions,
            "missing_fields": self.missing_fields,
            "diagnostics": self.diagnostics,
        }


@dataclass
class Remapping:
    """A suggested column re-assignment to recover blocked rows (question 4)."""

    needed_field: str
    blocks: str
    candidate_columns: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "needed_field": self.needed_field,
            "blocks": self.blocks,
            "candidate_columns": self.candidate_columns,
        }


@dataclass
class ImportDiagnostics:
    """Everything the importer knows about how it read one file."""

    # Q1 — confidently identified
    detected_institution: str
    header_row_index: int
    overall_mapping_confidence: float
    field_map: list[FieldMapEntry] = field(default_factory=list)
    state_counts: dict[str, int] = field(default_factory=dict)
    total_rows: int = 0
    persisted_rows: int = 0

    # Q2 + Q3 — inferred / missing (per row)
    row_notes: list[RowNote] = field(default_factory=list)

    # Q4 — minimum correction
    suggested_remappings: list[Remapping] = field(default_factory=list)

    # extraction provenance (handy for the UI; cheap to carry)
    fmt: str = ""
    n_preamble_skipped: int = 0
    n_footer_dropped: int = 0
    n_repeated_headers_suppressed: int = 0
    unmapped_columns: list[str] = field(default_factory=list)

    @property
    def counts_consistent(self) -> bool:
        """The four state buckets must account for every input row."""
        return sum(self.state_counts.values()) == self.total_rows

    def to_dict(self) -> dict[str, Any]:
        return {
            "detected_institution": self.detected_institution,
            "header_row_index": self.header_row_index,
            "overall_mapping_confidence": round(self.overall_mapping_confidence, 3),
            "field_map": [e.to_dict() for e in self.field_map],
            "state_counts": dict(self.state_counts),
            "total_rows": self.total_rows,
            "persisted_rows": self.persisted_rows,
            "row_notes": [n.to_dict() for n in self.row_notes],
            "suggested_remappings": [r.to_dict() for r in self.suggested_remappings],
            "fmt": self.fmt,
            "n_preamble_skipped": self.n_preamble_skipped,
            "n_footer_dropped": self.n_footer_dropped,
            "n_repeated_headers_suppressed": self.n_repeated_headers_suppressed,
            "unmapped_columns": self.unmapped_columns,
        }


@dataclass
class ImportResult:
    """Engine-side import outcome: persisted rows + diagnostics + skipped count.

    Distinct from `backend.models.ImportResult` (the API response model); this is
    the internal hand-off shape, deliberately mirroring Item 0's
    `ValidationResult` (a list + a skipped count) so the endpoint handles the
    generic lane and the named lane the same way.
    """

    transactions: list["Transaction"] = field(default_factory=list)
    diagnostics: ImportDiagnostics | None = None
    skipped_rows: int = 0


# --------------------------------------------------------------------------- #
# Builder                                                                      #
# --------------------------------------------------------------------------- #

# Empty per-state scaffold so every bucket is always present (and sums cleanly).
def _empty_state_counts() -> dict[str, int]:
    return {s.value: 0 for s in RowState}


def build_diagnostics(
    extracted: "ExtractedTable",
    mapping: "MappingResult",
    classified: list["ClassifiedRow"],
    *,
    institution: str,
    persisted_rows: int,
) -> ImportDiagnostics:
    """Assemble an `ImportDiagnostics` from the pipeline's intermediate results."""
    header = mapping.header or extracted.header

    field_map = [
        FieldMapEntry(
            field=fld.value,
            column_index=col,
            column_name=(header[col] if 0 <= col < len(header) else f"col{col}"),
            confidence=mapping.field_confidence.get(fld, 0.0),
            method=mapping.method_by_field.get(fld, "?"),
        )
        for fld, col in mapping.mapping.items()
    ]

    state_counts = _empty_state_counts()
    row_notes: list[RowNote] = []
    for i, cr in enumerate(classified):
        state_counts[cr.state.value] += 1
        # Only record a note for rows that actually carry inference or gaps.
        assumptions = list(cr.normalized.derivations) + list(cr.normalized.assumptions)
        if cr.action_inferred:
            assumptions.append(f"action inferred as {cr.canonical_action.value}")
        if assumptions or cr.missing_fields or cr.state in (RowState.PARTIAL, RowState.UNMAPPED):
            row_notes.append(
                RowNote(
                    row_index=i,
                    state=cr.state.value,
                    assumptions=assumptions,
                    missing_fields=list(cr.missing_fields),
                    diagnostics=list(cr.diagnostics),
                )
            )

    suggested = _suggest_remappings(mapping, classified, header)

    unmapped_cols = [
        (header[c] if 0 <= c < len(header) else f"col{c}") for c in mapping.unmapped_columns
    ]

    return ImportDiagnostics(
        detected_institution=institution,
        header_row_index=extracted.header_row_index,
        overall_mapping_confidence=mapping.overall_confidence,
        field_map=field_map,
        state_counts=state_counts,
        total_rows=len(classified),
        persisted_rows=persisted_rows,
        row_notes=row_notes,
        suggested_remappings=suggested,
        fmt=extracted.fmt,
        n_preamble_skipped=extracted.n_preamble_skipped,
        n_footer_dropped=extracted.n_footer_dropped,
        n_repeated_headers_suppressed=extracted.n_repeated_headers_suppressed,
        unmapped_columns=unmapped_cols,
    )


def _suggest_remappings(
    mapping: "MappingResult",
    classified: list["ClassifiedRow"],
    header: list[str],
) -> list[Remapping]:
    """Smallest column re-assignments that would unblock PARTIAL/UNMAPPED rows.

    For every required field/group the file failed to satisfy, offer the
    currently-unmapped columns as candidate sources for the Step 7 editor. The
    "blocks" string is taken from a representative blocked row's diagnostics.
    """
    blocked = [
        cr for cr in classified if cr.state in (RowState.PARTIAL, RowState.UNMAPPED)
    ]
    if not blocked:
        return []

    # Collect distinct missing-field tokens across all blocked rows.
    gap_tokens: dict[str, str] = {}
    for cr in blocked:
        for tok, diag in zip(cr.missing_fields, cr.diagnostics):
            gap_tokens.setdefault(tok, diag)
    # Also surface file-level gaps the classifier flagged.
    for tok in mapping.missing_required:
        gap_tokens.setdefault(tok, "")

    candidates = [
        {"column_index": c, "column_name": (header[c] if 0 <= c < len(header) else f"col{c}")}
        for c in mapping.unmapped_columns
    ]

    out: list[Remapping] = []
    for tok, diag in gap_tokens.items():
        blocks = diag.split("blocks ", 1)[1] if "blocks " in diag else "import completeness"
        out.append(Remapping(needed_field=tok, blocks=blocks, candidate_columns=candidates))
    return out


# --------------------------------------------------------------------------- #
# Last-diagnostics stash (parser → endpoint hand-off)                          #
# --------------------------------------------------------------------------- #

_LAST_DIAGNOSTICS: ImportDiagnostics | None = None


def set_last_diagnostics(d: ImportDiagnostics | None) -> None:
    """Record the diagnostics from the most recent generic parse."""
    global _LAST_DIAGNOSTICS
    _LAST_DIAGNOSTICS = d


def pop_last_diagnostics() -> ImportDiagnostics | None:
    """Return and clear the stashed diagnostics (one-shot, endpoint-consumed)."""
    global _LAST_DIAGNOSTICS
    d = _LAST_DIAGNOSTICS
    _LAST_DIAGNOSTICS = None
    return d
