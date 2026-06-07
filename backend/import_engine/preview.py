"""Editable column-mapping preview for the universal import lane (Item 4, Step 7).

The safety net. When a file falls to the generic lane (no named parser clears the
0.70 routing threshold), we DON'T silently import a best-guess mapping — we run
the pipeline up to but NOT including persistence, stash the extracted rows + the
auto-detected `MappingResult` in a short-lived server-side session, and hand the
frontend everything its mapping editor needs:

    detect_broker  → named (≥0.70) short-circuits; the endpoint sends the caller
                     straight to /api/import unchanged.
    extract        → locate table + header (table_extract)
    classify_columns → auto field↔column map with per-field confidence
    classify_table → four-state row outcome (for the preview row-state counts)
    build_diagnostics → the same ImportDiagnostics the live lane produces

`POST /api/import/preview` returns a `token` plus the editor payload; the user
tweaks the mapping and `POST /api/import/confirm` re-runs classify with the
user's overrides applied, then the FULL back half (normalize → classify → FX →
validate → dedup → store). Tokens are one-shot and expire after 30 minutes.

A confirmed mapping is persisted per *institution fingerprint* (a hash of the
normalized header row) so the next import of the same layout reuses it without
re-prompting.

This module owns only the engine-side mechanics (sessions, overrides,
fingerprint memory, the confirm pipeline). The FastAPI handlers live in
`backend.main`. No FastAPI imports here — keep it unit-testable in isolation.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from backend.import_engine.aliases import normalize_label
from backend.import_engine.canonical import (
    FILE_LEVEL_RULE,
    CanonicalField,
    requirement_gaps,
)
from backend.import_engine.classify_columns import MappingResult, classify_columns
from backend.import_engine.classify_tx import RowState, classify_table
from backend.import_engine.diagnostics import ImportDiagnostics, build_diagnostics
from backend.import_engine.table_extract import ExtractedTable, extract

if TYPE_CHECKING:
    from backend.models import Transaction

logger = logging.getLogger(__name__)

_F = CanonicalField

# Detection-confidence routing threshold (a named constant, mirrored in the
# frontend as REVIEW_CONFIDENCE_THRESHOLD). At or above this, a named parser
# owns the file and the upload skips the mapping editor entirely; below it, the
# file is generic and routes through preview → editor.
REVIEW_CONFIDENCE_THRESHOLD = 0.70

# Preview sessions live this long before a confirm is refused as expired.
SESSION_TTL_SECONDS = 30 * 60

# How many raw data rows to ship to the editor's preview table.
SAMPLE_ROW_LIMIT = 8

# app_state key prefix for the per-fingerprint confirmed-mapping memory.
_FINGERPRINT_KEY = "import_mapping::"

# Canonical fields the editor always offers a row for, in display order. A field
# outside this list still appears if the classifier mapped it.
_EDITOR_FIELD_ORDER: tuple[CanonicalField, ...] = (
    _F.TRANSACTION_DATE, _F.SETTLEMENT_DATE, _F.ACTION, _F.TICKER, _F.SECURITY_NAME,
    _F.QUANTITY, _F.PRICE, _F.GROSS_AMOUNT, _F.COMMISSION, _F.NET_AMOUNT,
    _F.DEBIT, _F.CREDIT, _F.CURRENCY, _F.ACCOUNT_TYPE, _F.ISIN, _F.EXCHANGE,
    _F.REFERENCE_ID,
)
# Always show a row for these even when unmapped, so the user can supply them.
_CORE_FIELDS = {
    _F.TRANSACTION_DATE, _F.ACTION, _F.TICKER, _F.QUANTITY, _F.PRICE,
    _F.NET_AMOUNT, _F.CURRENCY,
}
# The hard anchor — its absence is the loudest warning in the editor.
_REQUIRED_FIELDS = {_F.TRANSACTION_DATE}


# --------------------------------------------------------------------------- #
# Errors                                                                       #
# --------------------------------------------------------------------------- #

class PreviewTokenUnknown(Exception):
    """No live session for this token (never issued, or expired → 404)."""


class PreviewTokenUsed(Exception):
    """Session already consumed by a prior confirm (→ 410 Gone)."""


# --------------------------------------------------------------------------- #
# Session store (in-memory, ephemeral)                                         #
# --------------------------------------------------------------------------- #

@dataclass
class _PreviewSession:
    token: str
    extracted: ExtractedTable
    mapping: MappingResult
    institution: str
    account_prefix: str
    fingerprint: str
    filename: str
    created_at: float
    used: bool = False


_SESSIONS: dict[str, _PreviewSession] = {}


def _prune(now: float | None = None) -> None:
    """Drop sessions past their TTL (used or not)."""
    now = now if now is not None else time.time()
    stale = [t for t, s in _SESSIONS.items() if now - s.created_at > SESSION_TTL_SECONDS]
    for t in stale:
        _SESSIONS.pop(t, None)


def clear_sessions() -> None:
    """Test hook: wipe all preview sessions."""
    _SESSIONS.clear()


# --------------------------------------------------------------------------- #
# Fingerprint memory (per-layout confirmed mapping)                            #
# --------------------------------------------------------------------------- #

def _fingerprint(header: list[str]) -> str:
    """Stable hash of the normalized header row — identifies a file layout."""
    import hashlib

    norm = "|".join(normalize_label(h) for h in header)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def _save_fingerprint_mapping(fingerprint: str, mapping: MappingResult) -> None:
    """Remember a confirmed field→column mapping for this layout."""
    from backend import store

    payload = {fld.value: col for fld, col in mapping.mapping.items()}
    try:
        store.set_state(_FINGERPRINT_KEY + fingerprint, json.dumps(payload))
    except Exception as e:  # persistence is best-effort, never fatal to an import
        logger.warning("Could not persist mapping for %s: %s", fingerprint, e)


def _load_fingerprint_mapping(fingerprint: str) -> dict[CanonicalField, int] | None:
    """Recall a previously-confirmed mapping for this layout, if any."""
    from backend import store

    try:
        raw = store.get_state(_FINGERPRINT_KEY + fingerprint)
    except Exception:
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    out: dict[CanonicalField, int] = {}
    for k, v in data.items():
        try:
            out[CanonicalField(k)] = int(v)
        except (ValueError, TypeError):
            continue
    return out or None


# --------------------------------------------------------------------------- #
# Override application                                                          #
# --------------------------------------------------------------------------- #

def apply_overrides(
    base: MappingResult,
    overrides: dict[str, int] | None,
    extracted: ExtractedTable,
) -> MappingResult:
    """Return a NEW MappingResult with the user's column overrides applied.

    `overrides` maps a canonical-field value → source column index. A column of
    `-1` (or None / out-of-range) unmaps the field ("— ignore —"). Assigning a
    column already used by another field evicts that other field, preserving the
    strict 1:1 field↔column invariant. Overridden fields get confidence 1.0 and
    method "manual".
    """
    header = base.header or extracted.header
    width = len(header)
    new_map = dict(base.mapping)
    field_conf = dict(base.field_confidence)
    method_by = dict(base.method_by_field)

    for field_name, col in (overrides or {}).items():
        try:
            fld = CanonicalField(field_name)
        except ValueError:
            continue
        # Clear the field's current assignment first.
        new_map.pop(fld, None)
        field_conf.pop(fld, None)
        method_by.pop(fld, None)
        if col is None or col < 0 or col >= width:
            continue  # "— ignore —" / out of range → leave unmapped
        # Evict any other field currently holding this column (1:1 invariant).
        for other in [f for f, c in new_map.items() if c == col and f != fld]:
            new_map.pop(other, None)
            field_conf.pop(other, None)
            method_by.pop(other, None)
        new_map[fld] = col
        field_conf[fld] = 1.0
        method_by[fld] = "manual"

    used = set(new_map.values())
    unmapped = [i for i in range(width) if i not in used]
    missing = requirement_gaps(set(new_map), FILE_LEVEL_RULE)
    return MappingResult(
        mapping=new_map,
        field_confidence=field_conf,
        method_by_field=method_by,
        overall_confidence=base.overall_confidence,
        missing_required=missing,
        unmapped_columns=unmapped,
        header=list(header),
    )


# --------------------------------------------------------------------------- #
# Preview                                                                       #
# --------------------------------------------------------------------------- #

def _count_persistable(classified) -> int:
    return sum(
        1 for cr in classified
        if cr.state in (RowState.CONFIDENT, RowState.WITH_ASSUMPTIONS)
    )


def _fields_payload(mapping: MappingResult, header: list[str]) -> list[dict[str, Any]]:
    """One editor row per canonical field that's mapped or is a core field."""
    rows: list[dict[str, Any]] = []
    shown: set[CanonicalField] = set()

    def entry(fld: CanonicalField) -> dict[str, Any]:
        col = mapping.mapping.get(fld)
        in_range = col is not None and 0 <= col < len(header)
        return {
            "field": fld.value,
            "col_index": col if in_range else None,
            "col_header": header[col] if in_range else None,
            "confidence": round(mapping.field_confidence.get(fld, 0.0), 3),
            "method": mapping.method_by_field.get(fld),
            "required": fld in _REQUIRED_FIELDS,
        }

    for fld in _EDITOR_FIELD_ORDER:
        if fld in mapping.mapping or fld in _CORE_FIELDS:
            rows.append(entry(fld))
            shown.add(fld)
    # Any mapped field outside the canonical order still gets a row.
    for fld in mapping.mapping:
        if fld not in shown:
            rows.append(entry(fld))
    return rows


def build_preview(file_path: str | Path, filename: str) -> dict[str, Any]:
    """Run the generic pipeline up to (not including) persistence.

    Returns a JSON-able payload for the mapping editor. The caller (endpoint)
    decides routing from `detected_confidence` vs REVIEW_CONFIDENCE_THRESHOLD:
    a named parser (≥ threshold) yields a `mode="named"` payload with no token,
    and the endpoint sends the user to /api/import unchanged.
    """
    # Lazy import: parsers.registry/generic depend on engine modules, so importing
    # at module top risks a load-time cycle when the package is initializing.
    from backend.parsers.generic import (
        _GENERIC_LABEL,
        _account_prefix,
        _detect_institution,
    )
    from backend.parsers.registry import detect_broker

    path = Path(file_path)
    broker, confidence = detect_broker(path)
    if confidence >= REVIEW_CONFIDENCE_THRESHOLD:
        # A named parser owns this file — no preview/editor needed.
        return {
            "mode": "named",
            "needs_review": False,
            "detected_broker": broker,
            "detected_confidence": round(confidence, 3),
        }

    et = extract(path)
    if not et.header or not et.rows:
        # Nothing tabular to map — let the standard /api/import path surface the
        # friendly "unrecognized format" error rather than an empty editor.
        return {
            "mode": "named",  # routes the caller to /api/import for the real error
            "needs_review": False,
            "detected_broker": broker,
            "detected_confidence": round(confidence, 3),
            "empty": True,
        }

    auto = classify_columns(et)
    fingerprint = _fingerprint(et.header)
    saved = _load_fingerprint_mapping(fingerprint)
    if saved is not None:
        mapping = apply_overrides(
            auto, {fld.value: col for fld, col in saved.items()}, et
        )
        reused = True
    else:
        mapping = auto
        reused = False

    classified = classify_table(et.rows, mapping)
    institution = _detect_institution(path) or _GENERIC_LABEL
    account_prefix = _account_prefix(path)
    diag = build_diagnostics(
        et, mapping, classified,
        institution=institution, persisted_rows=_count_persistable(classified),
    )

    token = uuid.uuid4().hex[:16]
    _prune()
    _SESSIONS[token] = _PreviewSession(
        token=token,
        extracted=et,
        mapping=mapping,
        institution=institution,
        account_prefix=account_prefix,
        fingerprint=fingerprint,
        filename=filename,
        created_at=time.time(),
    )

    header = mapping.header or et.header
    return {
        "mode": "generic",
        # A remembered layout is trusted: skip the editor, auto-confirm via token.
        "needs_review": not reused,
        "reused_saved_mapping": reused,
        "token": token,
        "detected_broker": "generic",
        "detected_confidence": round(confidence, 3),
        "detected_institution": institution,
        "overall_mapping_confidence": round(mapping.overall_confidence, 3),
        "source_columns": [
            {"index": i, "header": h} for i, h in enumerate(header)
        ],
        "fields": _fields_payload(mapping, header),
        "sample_rows": [list(r) for r in et.rows[:SAMPLE_ROW_LIMIT]],
        "row_state_counts": dict(diag.state_counts),
        "missing_required": list(mapping.missing_required),
        "suggested_remappings": [r.to_dict() for r in diag.suggested_remappings],
    }


# --------------------------------------------------------------------------- #
# Confirm                                                                       #
# --------------------------------------------------------------------------- #

def confirm_preview(
    token: str,
    overrides: dict[str, int] | None = None,
) -> tuple[list["Transaction"], ImportDiagnostics, str]:
    """Re-run the pipeline with overrides; return (txs, diagnostics, filename).

    Builds FX-populated `Transaction`s for the CONFIDENT/WITH_ASSUMPTIONS rows
    only — PARTIAL/UNMAPPED stay in diagnostics, never persisted. The caller runs
    the shared back half (validate → dedup → store). The session is consumed
    (one-shot) and the confirmed mapping is remembered for this layout.

    Raises PreviewTokenUnknown (404) or PreviewTokenUsed (410).
    """
    from backend.fx import get_fx_service
    from backend.parsers.generic import _build_transaction

    _prune()
    session = _SESSIONS.get(token)
    if session is None:
        raise PreviewTokenUnknown(token)
    if session.used:
        raise PreviewTokenUsed(token)
    session.used = True  # one-shot: a re-confirm now hits PreviewTokenUsed

    patched = apply_overrides(session.mapping, overrides, session.extracted)
    classified = classify_table(session.extracted.rows, patched)

    fx = get_fx_service()
    txs: list["Transaction"] = []
    for cr in classified:
        if cr.state not in (RowState.CONFIDENT, RowState.WITH_ASSUMPTIONS):
            continue
        t = _build_transaction(
            cr, session.account_prefix, session.institution, session.filename
        )
        if t is None:
            continue
        fx.populate_transaction(t)
        txs.append(t)

    diag = build_diagnostics(
        session.extracted, patched, classified,
        institution=session.institution, persisted_rows=len(txs),
    )
    # Remember the confirmed layout so the next identical import skips the editor.
    _save_fingerprint_mapping(session.fingerprint, patched)
    return txs, diag, session.filename
