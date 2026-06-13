"""Canonical schema for the universal import lane (Item 4, Step 1).

THREE things live here:

1. `CanonicalField` — the canonical column vocabulary the classifier maps a
   file's columns onto (date, action, ticker, quantity, price, amounts, …).

2. A TWO-LAYER action model (Step 0 Decision A):
     - `CanonicalAction` — a RICH 16-label taxonomy used ONLY for diagnostics /
       traceability inside the import engine. It lets the importer describe what
       it thinks a row is with more nuance than the app stores.
     - `ACTION_DOWNMAP` / `to_emitted_action()` — maps each rich label DOWN to
       the existing 11-value `backend.models.Action` Literal, which is the ONLY
       vocabulary that reaches store / ACB / reports / `types.ts`. We do NOT
       expand `Action` app-wide in 0.7.0 — generic rows always emit one of the 11.

3. `MIN_SCHEMA` — the §4 per-action minimum-field ruleset that Step 4 consumes to
   assign each row its four-state outcome (confidently mapped / mapped with
   assumptions / partially mapped / unmapped).

Pure data + tiny helpers. No I/O, no pandas, no parsing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


# --------------------------------------------------------------------------- #
# Canonical column fields                                                      #
# --------------------------------------------------------------------------- #

class CanonicalField(str, Enum):
    """Every column the classifier can map a source column onto."""

    TRANSACTION_DATE = "transaction_date"
    SETTLEMENT_DATE = "settlement_date"
    ACTION = "action"
    TICKER = "ticker"
    SECURITY_NAME = "security_name"
    QUANTITY = "quantity"
    PRICE = "price"
    GROSS_AMOUNT = "gross_amount"
    COMMISSION = "commission"
    NET_AMOUNT = "net_amount"
    DEBIT = "debit"          # combined with CREDIT into a signed net_amount
    CREDIT = "credit"
    CURRENCY = "currency"
    FX_RATE = "fx_rate"
    ACCOUNT = "account"
    ACCOUNT_TYPE = "account_type"
    ISIN = "isin"
    EXCHANGE = "exchange"
    REFERENCE_ID = "reference_id"


# --------------------------------------------------------------------------- #
# Action taxonomy — rich internal labels + down-map to the stored 11           #
# --------------------------------------------------------------------------- #

class CanonicalAction(str, Enum):
    """Rich internal action taxonomy (16 labels) — diagnostics/traceability only.

    NEVER stored directly on a Transaction. Always passed through
    `to_emitted_action()` first.
    """

    CONTRIBUTION = "contribution"
    WITHDRAWAL = "withdrawal"
    BUY = "buy"
    SELL = "sell"
    DIVIDEND = "dividend"
    FEE = "fee"
    INTEREST = "interest"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"
    REINVEST_DRIP = "reinvest_drip"
    SPLIT = "split"
    CORPORATE_ACTION = "corporate_action"
    JOURNAL = "journal"
    RETURN_OF_CAPITAL = "return_of_capital"
    TAX_WITHHOLDING = "tax_withholding"
    CASH_ADJUSTMENT = "cash_adjustment"


# The 11 emitted actions — MUST mirror backend.models.Action exactly. A unit test
# asserts this stays in sync so a future edit to models.Action can't drift.
EMITTED_ACTIONS: frozenset[str] = frozenset(
    {
        "BUY",
        "SELL",
        "DIVIDEND",
        "DEPOSIT",
        "WITHDRAWAL",
        "CONTRIBUTION",
        "FEE",
        "SPLIT",
        "INTEREST",
        "TRANSFER",
        "OTHER",
    }
)


# Rich label -> emitted Action Literal. The ONLY vocabulary that reaches the DB.
#   transfer_in   -> DEPOSIT      (cash/securities arriving)
#   transfer_out  -> WITHDRAWAL   (cash/securities leaving)
#   reinvest_drip -> BUY          (a DRIP is a purchase; ACB must see it as a buy)
#   journal       -> TRANSFER     (security journalled between accounts; excluded
#                                  from Modified-Dietz cash flows, like other TRANSFERs)
#   corporate_action / return_of_capital / tax_withholding / cash_adjustment
#                 -> OTHER        (no first-class handling; preserved, not misclassified)
ACTION_DOWNMAP: dict[CanonicalAction, str] = {
    CanonicalAction.CONTRIBUTION: "CONTRIBUTION",
    CanonicalAction.WITHDRAWAL: "WITHDRAWAL",
    CanonicalAction.BUY: "BUY",
    CanonicalAction.SELL: "SELL",
    CanonicalAction.DIVIDEND: "DIVIDEND",
    CanonicalAction.FEE: "FEE",
    CanonicalAction.INTEREST: "INTEREST",
    CanonicalAction.TRANSFER_IN: "DEPOSIT",
    CanonicalAction.TRANSFER_OUT: "WITHDRAWAL",
    CanonicalAction.REINVEST_DRIP: "BUY",
    CanonicalAction.SPLIT: "SPLIT",
    CanonicalAction.CORPORATE_ACTION: "OTHER",
    CanonicalAction.JOURNAL: "TRANSFER",
    CanonicalAction.RETURN_OF_CAPITAL: "OTHER",
    CanonicalAction.TAX_WITHHOLDING: "OTHER",
    CanonicalAction.CASH_ADJUSTMENT: "OTHER",
}


def to_emitted_action(action: CanonicalAction) -> str:
    """Map a rich canonical action down to the stored `Action` Literal.

    Raises KeyError if a CanonicalAction is missing from the down-map (a unit
    test guards full coverage, so this can't happen at runtime once green).
    """
    emitted = ACTION_DOWNMAP[action]
    # Contract guard: the down-map can only ever yield one of the stored 11.
    assert emitted in EMITTED_ACTIONS, f"down-map produced non-stored action {emitted!r}"
    return emitted


# --------------------------------------------------------------------------- #
# Per-action minimum-field ruleset (§4) → drives the four-state outcome        #
# --------------------------------------------------------------------------- #

# Sign expectations are advisory hints for the normalizer/classifier, NOT hard
# rejects: e.g. a dividend's net_amount is normally > 0.
Sign = str  # "positive" | "negative" | "signed" | "any"


@dataclass(frozen=True)
class MinSchemaRule:
    """Minimum-field contract for one canonical action.

    Semantics (interpreted by Step 4):
      - `required`     : each field must be present OR derivable.
      - `any_of`       : each inner tuple is a group where >= 1 field must be present.
      - `n_of`         : each (n, fields) group needs >= n of `fields` present.
      - `requires_if_present` : each (trigger, fields) pair is a CONDITIONAL
                         requirement — IF `trigger` is present, every field in
                         `fields` must also be present. Absent trigger == no
                         requirement. This is how one action can carry two
                         alternative shapes (BUG-003: a transfer is EITHER cash
                         [date + net_amount] OR in-kind [date + ticker + quantity]
                         — the ticker is the evidence that selects the in-kind
                         contract).
      - `derivable`    : fields the normalizer may compute when absent (logged as
                         an assumption, moving the row to "mapped with assumptions").
      - `recommended`  : nice-to-have; absence never blocks, only annotates.
      - `review_if_absent` : human-readable reasons that force the row to
                         "partially mapped" / "unmapped".
      - `sign_hints`   : advisory expected sign per field.
    """

    action: CanonicalAction
    required: tuple[CanonicalField, ...] = ()
    any_of: tuple[tuple[CanonicalField, ...], ...] = ()
    n_of: tuple[tuple[int, tuple[CanonicalField, ...]], ...] = ()
    requires_if_present: tuple[tuple[CanonicalField, tuple[CanonicalField, ...]], ...] = ()
    derivable: tuple[CanonicalField, ...] = ()
    recommended: tuple[CanonicalField, ...] = ()
    review_if_absent: tuple[str, ...] = ()
    sign_hints: dict[CanonicalField, Sign] = field(default_factory=dict)


_F = CanonicalField  # local alias for brevity in the table below
_A = CanonicalAction

MIN_SCHEMA: dict[CanonicalAction, MinSchemaRule] = {
    _A.CONTRIBUTION: MinSchemaRule(
        _A.CONTRIBUTION,
        required=(_F.TRANSACTION_DATE, _F.NET_AMOUNT),
        derivable=(_F.ACTION,),
        recommended=(_F.ACCOUNT, _F.CURRENCY),
        review_if_absent=("net_amount unparseable",),
        sign_hints={_F.NET_AMOUNT: "positive"},
    ),
    _A.WITHDRAWAL: MinSchemaRule(
        _A.WITHDRAWAL,
        required=(_F.TRANSACTION_DATE, _F.NET_AMOUNT),
        derivable=(_F.ACTION,),
        recommended=(_F.ACCOUNT, _F.CURRENCY),
        review_if_absent=("net_amount unparseable",),
        sign_hints={_F.NET_AMOUNT: "negative"},
    ),
    _A.BUY: MinSchemaRule(
        _A.BUY,
        required=(_F.TRANSACTION_DATE,),
        any_of=((_F.TICKER, _F.SECURITY_NAME),),
        n_of=((2, (_F.QUANTITY, _F.PRICE, _F.NET_AMOUNT)),),
        derivable=(_F.QUANTITY, _F.PRICE, _F.NET_AMOUNT, _F.ACTION),
        recommended=(_F.COMMISSION, _F.ACCOUNT_TYPE, _F.CURRENCY, _F.SETTLEMENT_DATE),
        review_if_absent=(
            "only one of {quantity, price, net_amount}",
            "no security identifier (ticker or security_name)",
        ),
        sign_hints={_F.NET_AMOUNT: "negative"},
    ),
    _A.SELL: MinSchemaRule(
        _A.SELL,
        required=(_F.TRANSACTION_DATE,),
        any_of=((_F.TICKER, _F.SECURITY_NAME),),
        n_of=((2, (_F.QUANTITY, _F.PRICE, _F.NET_AMOUNT)),),
        derivable=(_F.QUANTITY, _F.PRICE, _F.NET_AMOUNT, _F.ACTION),
        recommended=(_F.COMMISSION, _F.ACCOUNT_TYPE, _F.CURRENCY, _F.SETTLEMENT_DATE),
        review_if_absent=(
            "only one of {quantity, price, net_amount}",
            "no security identifier (ticker or security_name)",
        ),
        sign_hints={_F.NET_AMOUNT: "positive"},
    ),
    _A.DIVIDEND: MinSchemaRule(
        _A.DIVIDEND,
        required=(_F.TRANSACTION_DATE, _F.NET_AMOUNT),
        derivable=(_F.TICKER,),  # from security_name if resolvable
        recommended=(_F.TICKER, _F.CURRENCY),
        review_if_absent=("no amount",),
        sign_hints={_F.NET_AMOUNT: "positive"},
    ),
    _A.REINVEST_DRIP: MinSchemaRule(
        _A.REINVEST_DRIP,
        required=(_F.TRANSACTION_DATE, _F.QUANTITY),
        any_of=((_F.TICKER, _F.SECURITY_NAME),),
        derivable=(_F.PRICE, _F.NET_AMOUNT),
        recommended=(_F.COMMISSION,),
        review_if_absent=("no quantity AND no amount",),
    ),
    _A.FEE: MinSchemaRule(
        _A.FEE,
        required=(_F.TRANSACTION_DATE, _F.NET_AMOUNT),
        recommended=(_F.TICKER,),
        review_if_absent=("no amount",),
        sign_hints={_F.NET_AMOUNT: "negative"},
    ),
    _A.INTEREST: MinSchemaRule(
        _A.INTEREST,
        required=(_F.TRANSACTION_DATE, _F.NET_AMOUNT),
        recommended=(_F.CURRENCY,),
        review_if_absent=("no amount",),
        sign_hints={_F.NET_AMOUNT: "positive"},
    ),
    # Transfers carry two alternative shapes (BUG-003):
    #   cash    : date + net_amount             (an ordinary Deposit/Withdrawal)
    #   in-kind : date + ticker + quantity      (securities moved between firms)
    # The any_of group demands ONE of the shapes' anchors (net_amount or ticker);
    # requires_if_present upgrades a row WITH a ticker to the in-kind contract
    # (quantity becomes mandatory). The old unconditional n_of=(2,(ticker,qty))
    # made plain cash deposits fail the schema and held them back as PARTIAL.
    _A.TRANSFER_IN: MinSchemaRule(
        _A.TRANSFER_IN,
        required=(_F.TRANSACTION_DATE,),
        any_of=((_F.NET_AMOUNT, _F.TICKER),),
        requires_if_present=((_F.TICKER, (_F.QUANTITY,)),),
        derivable=(_F.ACTION,),
        recommended=(_F.ACCOUNT, _F.ACCOUNT_TYPE),
        review_if_absent=("neither security+qty nor amount",),
    ),
    _A.TRANSFER_OUT: MinSchemaRule(
        _A.TRANSFER_OUT,
        required=(_F.TRANSACTION_DATE,),
        any_of=((_F.NET_AMOUNT, _F.TICKER),),
        requires_if_present=((_F.TICKER, (_F.QUANTITY,)),),
        derivable=(_F.ACTION,),
        recommended=(_F.ACCOUNT, _F.ACCOUNT_TYPE),
        review_if_absent=("neither security+qty nor amount",),
    ),
    _A.SPLIT: MinSchemaRule(
        _A.SPLIT,
        required=(_F.TRANSACTION_DATE,),
        any_of=((_F.TICKER, _F.SECURITY_NAME),),
        recommended=(_F.EXCHANGE, _F.QUANTITY),
        review_if_absent=("no split ratio AND no pre/post quantity clue",),
    ),
    _A.CORPORATE_ACTION: MinSchemaRule(
        _A.CORPORATE_ACTION,
        required=(_F.TRANSACTION_DATE,),
        any_of=((_F.TICKER, _F.SECURITY_NAME),),
        recommended=(_F.SECURITY_NAME,),
        review_if_absent=("no security identifier",),
    ),
    _A.JOURNAL: MinSchemaRule(
        _A.JOURNAL,
        required=(_F.TRANSACTION_DATE, _F.QUANTITY),
        any_of=((_F.TICKER, _F.SECURITY_NAME),),
        recommended=(_F.ACCOUNT_TYPE, _F.ACCOUNT),
        review_if_absent=("no quantity",),
    ),
    _A.RETURN_OF_CAPITAL: MinSchemaRule(
        _A.RETURN_OF_CAPITAL,
        required=(_F.TRANSACTION_DATE, _F.NET_AMOUNT),
        any_of=((_F.TICKER, _F.SECURITY_NAME),),
        review_if_absent=("no amount",),
    ),
    _A.TAX_WITHHOLDING: MinSchemaRule(
        _A.TAX_WITHHOLDING,
        required=(_F.TRANSACTION_DATE, _F.NET_AMOUNT),
        recommended=(_F.TICKER, _F.CURRENCY),
        review_if_absent=("no amount",),
        sign_hints={_F.NET_AMOUNT: "negative"},
    ),
    _A.CASH_ADJUSTMENT: MinSchemaRule(
        _A.CASH_ADJUSTMENT,
        required=(_F.TRANSACTION_DATE, _F.NET_AMOUNT),
        derivable=(_F.ACTION,),  # falls back to cash_adjustment when nothing else fits
        recommended=(_F.REFERENCE_ID,),
        review_if_absent=("no amount AND no date",),
    ),
}


# Global minimum every row must meet regardless of action (§4 "Global minimum"):
# a parseable transaction_date AND either an explicit action or enough signal to
# infer one. Encoded for Step 4 to reference.
GLOBAL_REQUIRED: tuple[CanonicalField, ...] = (_F.TRANSACTION_DATE,)
GLOBAL_ACTION_OR_INFERABLE: tuple[CanonicalField, ...] = (
    _F.ACTION,
    _F.NET_AMOUNT,
    _F.QUANTITY,
    _F.TICKER,
)


def rule_for(action: CanonicalAction) -> MinSchemaRule:
    """Look up the minimum-field rule for a canonical action."""
    return MIN_SCHEMA[action]


def requirement_gaps(mapped: set[CanonicalField], rule: MinSchemaRule) -> list[str]:
    """Evaluate a set of present fields against a MinSchemaRule's hard contract.

    Returns a list of unmet-requirement tokens (empty == fully satisfied):
      - a missing `required` field            → that field's value, e.g. "net_amount"
      - an unsatisfied `any_of` group          → "a|b|c" (need at least one of)
      - an unsatisfied `n_of` group            → "2_of:a|b|c" (need at least n of)
      - an unmet `requires_if_present` clause  → "a_with_b" (a required because b
        is present), e.g. "quantity_with_ticker"

    Used by the column classifier (file-level, against FILE_LEVEL_RULE) and by
    Step 4 (per-row, against the row's action rule). `derivable` fields are NOT
    treated as satisfied here — presence is what's checked; Step 4 layers
    derivation on top before deciding a row is unmappable.
    """
    gaps: list[str] = []
    for f in rule.required:
        if f not in mapped:
            gaps.append(f.value)
    for group in rule.any_of:
        if not any(f in mapped for f in group):
            gaps.append("|".join(f.value for f in group))
    for n, group in rule.n_of:
        if sum(1 for f in group if f in mapped) < n:
            gaps.append(f"{n}_of:" + "|".join(f.value for f in group))
    for trigger, fields in rule.requires_if_present:
        if trigger in mapped:
            for f in fields:
                if f not in mapped:
                    gaps.append(f"{f.value}_with_{trigger.value}")
    return gaps


# A synthetic rule for FILE-LEVEL mapping validation (used by the column
# classifier): a usable transaction table needs a date column (trade OR
# settlement) AND at least one transactional signal column.
FILE_LEVEL_RULE = MinSchemaRule(
    action=_A.CASH_ADJUSTMENT,  # placeholder; only the field groups matter here
    any_of=(
        (_F.TRANSACTION_DATE, _F.SETTLEMENT_DATE),
        (_F.ACTION, _F.NET_AMOUNT, _F.DEBIT, _F.CREDIT, _F.QUANTITY, _F.TICKER),
    ),
)
