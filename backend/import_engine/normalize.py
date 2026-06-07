"""Row normalizer for the universal import lane (Item 4, Step 4).

Takes ONE raw data row plus the column `MappingResult` from Step 3 and produces a
`NormalizedRow`: canonical field values after cleaning, with a record of every
derivation and assumption applied so `ImportDiagnostics` (Step 5) can surface them.

This module deliberately REUSES the broker-parser helpers in
`backend.parsers._common` instead of re-implementing them:

  - `safe_float`   — currency-formatted floats, brackets `(123.45)` → negative,
                     thousands separators, `$£€¥`/ISO-code stripping.
  - `parse_date`   — every date format the brokers ship.
  - `guess_currency` / `guess_exchange` / `guess_account_type` — light inference.
  - `normalize_action` — keyword + shape action vocabulary (used by Step 4's
                     classifier, not here, but the sign conventions agree).

What normalization does, beyond per-cell cleaning:

  * debit / credit split columns → a single signed `net_amount`
    (credit = inflow +, debit = outflow −).
  * bracketed / parenthesised negatives  → handled by `safe_float`.
  * a missing minus sign on an outflow action (BUY / FEE / WITHDRAWAL / …) is
    inferred from the action keyword and recorded as an assumption.
  * signed-quantity conventions (Interactive-Brokers-style: a buy carries a
    NEGATIVE quantity) → quantity is stored as a magnitude; direction is left to
    the net-amount sign / action, which is how `normalize_action` reads it.
  * `net_amount` derived from `quantity × price` when the file gives neither a net
    nor a debit/credit column.
  * `settlement_date` → `transaction_date` fallback, `exchange` from a ticker
    suffix — each logged.

Every derivation/assumption is appended to `derivations` / `assumptions` as a
human-readable line. Pure transformation: no I/O, no DB, no network.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Sequence

from backend.import_engine.canonical import CanonicalField
from backend.import_engine.classify_columns import MappingResult
from backend.parsers._common import (
    guess_account_type,
    guess_currency,
    guess_exchange,
    normalize_action,
    parse_date,
    safe_float,
)

_F = CanonicalField

# Blank-ish cell tokens that should NOT count as a present value.
_BLANK_TOKENS = {"", "-", "—", "n/a", "na", "nan", "null", "none"}

# Field groups by coercion type.
_DATE_FIELDS = (_F.TRANSACTION_DATE, _F.SETTLEMENT_DATE)
_NUMERIC_FIELDS = (
    _F.QUANTITY,
    _F.PRICE,
    _F.GROSS_AMOUNT,
    _F.COMMISSION,
    _F.NET_AMOUNT,
    _F.DEBIT,
    _F.CREDIT,
    _F.FX_RATE,
)
_STRING_FIELDS = (
    _F.ACTION,
    _F.TICKER,
    _F.SECURITY_NAME,
    _F.CURRENCY,
    _F.ACCOUNT,
    _F.ACCOUNT_TYPE,
    _F.ISIN,
    _F.EXCHANGE,
    _F.REFERENCE_ID,
)

# Emitted-action keywords whose cash flow is an OUTFLOW (net_amount should be < 0).
_OUTFLOW_ACTIONS = {"BUY", "FEE", "WITHDRAWAL"}
# … and INFLOW (net_amount should be > 0).
_INFLOW_ACTIONS = {"SELL", "DIVIDEND", "DEPOSIT", "CONTRIBUTION", "INTEREST"}


@dataclass
class NormalizedRow:
    """One raw row after canonical cleaning.

    `values` holds only fields that ended up with a usable value (whether read
    directly from the source or derived). `present` / `derived` partition those
    keys so Step 4 can tell a confidently-read field from an assumed one.
    """

    values: dict[CanonicalField, Any] = field(default_factory=dict)
    raw: dict[CanonicalField, str] = field(default_factory=dict)
    present: set[CanonicalField] = field(default_factory=set)
    derived: set[CanonicalField] = field(default_factory=set)
    derivations: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    quantity_sign: int = 0  # original sign of the source quantity (-1/0/+1)

    # -- convenience accessors ------------------------------------------------ #
    def get(self, f: CanonicalField, default: Any = None) -> Any:
        return self.values.get(f, default)

    @property
    def mapped_fields(self) -> set[CanonicalField]:
        """Fields that carry a value, present OR derived — what Step 4 checks
        against the per-action MIN_SCHEMA contract."""
        return set(self.values)

    @property
    def has_derivations(self) -> bool:
        return bool(self.derivations or self.assumptions)


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _cell(row: Sequence[str], col: int | None) -> str:
    if col is None or col < 0 or col >= len(row):
        return ""
    v = row[col]
    return v.strip() if isinstance(v, str) else str(v).strip()


def _is_blank(text: str) -> bool:
    return text.strip().lower() in _BLANK_TOKENS


def _provisional_action(raw_action: str, abs_qty: float, net: float) -> str:
    """Best-guess emitted action from a raw label + shape, for sign inference."""
    return normalize_action(raw_action or None, quantity=abs_qty, net=net)


# --------------------------------------------------------------------------- #
# Normalization                                                               #
# --------------------------------------------------------------------------- #

def normalize_row(row: Sequence[str], mapping: MappingResult) -> NormalizedRow:
    """Clean one raw data row into a `NormalizedRow` using a Step-3 mapping.

    `row` is a list of cell strings (an `ExtractedTable.rows` entry); `mapping`
    is the `MappingResult` whose `.mapping` gives `{CanonicalField: column}`.
    """
    out = NormalizedRow()
    cols = mapping.mapping

    # Capture raw text for every mapped, non-blank field (diagnostics + inference).
    for fld, col in cols.items():
        txt = _cell(row, col)
        if not _is_blank(txt):
            out.raw[fld] = txt

    # ---- dates -------------------------------------------------------------- #
    for fld in _DATE_FIELDS:
        txt = out.raw.get(fld)
        if txt:
            d = parse_date(txt)
            if isinstance(d, date):
                out.values[fld] = d
                out.present.add(fld)
    # settlement → transaction fallback
    if _F.TRANSACTION_DATE not in out.values and _F.SETTLEMENT_DATE in out.values:
        out.values[_F.TRANSACTION_DATE] = out.values[_F.SETTLEMENT_DATE]
        out.derived.add(_F.TRANSACTION_DATE)
        out.derivations.append("transaction_date derived from settlement_date")

    # ---- numerics ----------------------------------------------------------- #
    for fld in _NUMERIC_FIELDS:
        txt = out.raw.get(fld)
        if txt is None:
            continue
        val = safe_float(txt)
        if fld == _F.QUANTITY:
            # Store magnitude; remember sign (IB-style signed quantity convention).
            out.quantity_sign = (val > 0) - (val < 0)
            out.values[_F.QUANTITY] = abs(val)
            out.present.add(_F.QUANTITY)
        else:
            out.values[fld] = val
            out.present.add(fld)

    # ---- strings ------------------------------------------------------------ #
    for fld in _STRING_FIELDS:
        txt = out.raw.get(fld)
        if not txt:
            continue
        if fld == _F.CURRENCY:
            out.values[fld] = guess_currency(txt)
        elif fld == _F.ACCOUNT_TYPE:
            out.values[fld] = guess_account_type(txt)
        elif fld in (_F.TICKER, _F.ISIN):
            out.values[fld] = txt.upper()
        else:
            out.values[fld] = txt
        out.present.add(fld)

    # ---- debit / credit → signed net_amount --------------------------------- #
    if _F.NET_AMOUNT not in out.values and (
        _F.DEBIT in out.values or _F.CREDIT in out.values
    ):
        credit = out.values.get(_F.CREDIT, 0.0)
        debit = out.values.get(_F.DEBIT, 0.0)
        # Debit columns are usually written as positive magnitudes; treat as outflow.
        net = credit - abs(debit)
        out.values[_F.NET_AMOUNT] = round(net, 4)
        out.derived.add(_F.NET_AMOUNT)
        out.derivations.append("net_amount derived from credit − debit")

    # ---- sign inference from action keyword --------------------------------- #
    raw_action = out.values.get(_F.ACTION, "")
    abs_qty = out.values.get(_F.QUANTITY, 0.0)
    net_now = out.values.get(_F.NET_AMOUNT, 0.0)
    prov = _provisional_action(raw_action, abs_qty, net_now)
    if _F.NET_AMOUNT in out.values:
        net = out.values[_F.NET_AMOUNT]
        if net > 0 and prov in _OUTFLOW_ACTIONS:
            out.values[_F.NET_AMOUNT] = -net
            out.assumptions.append(
                f"net_amount sign set negative to match {prov.lower()} action"
            )
        elif net < 0 and prov in _INFLOW_ACTIONS:
            out.values[_F.NET_AMOUNT] = -net
            out.assumptions.append(
                f"net_amount sign set positive to match {prov.lower()} action"
            )

    # ---- derive net_amount / gross from quantity × price -------------------- #
    # Only when the file gave NO net (and no debit/credit to build one from);
    # an already-present net is authoritative and must not be overwritten.
    abs_qty = out.values.get(_F.QUANTITY, 0.0)
    price = out.values.get(_F.PRICE, 0.0)
    if _F.NET_AMOUNT not in out.values and abs_qty and price:
        magnitude = round(abs_qty * price, 4)
        outflow = prov in _OUTFLOW_ACTIONS
        signed = -magnitude if outflow else magnitude
        if _F.GROSS_AMOUNT not in out.values:
            out.values[_F.GROSS_AMOUNT] = signed
            out.derived.add(_F.GROSS_AMOUNT)
            out.derivations.append("gross_amount derived from quantity × price")
        commission = abs(out.values.get(_F.COMMISSION, 0.0))
        net = signed - commission if outflow else signed - commission
        out.values[_F.NET_AMOUNT] = round(net, 4)
        out.derived.add(_F.NET_AMOUNT)
        out.derivations.append(
            "net_amount derived from quantity × price"
            + (" − commission" if commission else "")
        )

    # ---- exchange from ticker suffix ---------------------------------------- #
    if _F.EXCHANGE not in out.values and _F.TICKER in out.values:
        exch = guess_exchange(out.values.get(_F.TICKER), out.values.get(_F.CURRENCY))
        if exch:
            out.values[_F.EXCHANGE] = exch
            out.derived.add(_F.EXCHANGE)
            out.derivations.append(f"exchange '{exch}' derived from ticker suffix")

    return out
