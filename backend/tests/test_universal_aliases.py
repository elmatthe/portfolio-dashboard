"""Item 4 Step 1 — bilingual header alias dictionary + normalization."""
from __future__ import annotations

import pytest

from backend.import_engine.aliases import (
    CANONICAL_ALIASES,
    match_label,
    normalize_label,
)
from backend.import_engine.canonical import CanonicalField as F


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Trade Date", "trade date"),
        ("  NET  AMOUNT ", "net amount"),
        ("Price ($)", "price"),
        ("Date d'exécution", "date d execution"),
        ("QUANTITÉ", "quantite"),
        ("Réglement", "reglement"),
        ("Symbol/Ticker", "symbol ticker"),
        (None, ""),
        ("", ""),
    ],
)
def test_normalize_label(raw, expected):
    assert normalize_label(raw) == expected


@pytest.mark.parametrize(
    "label,field",
    [
        # English
        ("Trade Date", F.TRANSACTION_DATE),
        ("Transaction Date", F.TRANSACTION_DATE),
        ("Settlement Date", F.SETTLEMENT_DATE),
        ("Activity Type", F.ACTION),
        ("Symbol", F.TICKER),
        ("Security Name", F.SECURITY_NAME),
        ("Quantity", F.QUANTITY),
        ("Price", F.PRICE),
        ("Commission", F.COMMISSION),
        ("Net Amount", F.NET_AMOUNT),
        ("Amount", F.NET_AMOUNT),  # §4: a lone "amount" maps to net_amount
        ("Gross Amount", F.GROSS_AMOUNT),
        ("Currency", F.CURRENCY),
        ("Exchange Rate", F.FX_RATE),
        ("Account Number", F.ACCOUNT),
        ("Account Type", F.ACCOUNT_TYPE),
        ("ISIN", F.ISIN),
    ],
)
def test_match_label_english(label, field):
    assert match_label(label) is field


@pytest.mark.parametrize(
    "label,field",
    [
        ("Quantité", F.QUANTITY),
        ("Prix", F.PRICE),
        ("Devise", F.CURRENCY),
        ("Date de règlement", F.SETTLEMENT_DATE),
        ("Type d'opération", F.ACTION),
        ("Montant net", F.NET_AMOUNT),
        ("Frais", F.COMMISSION),
        ("Symbole", F.TICKER),
        ("Numéro de compte", F.ACCOUNT),
    ],
)
def test_match_label_french(label, field):
    assert match_label(label) is field


@pytest.mark.parametrize(
    "label,field",
    [
        ("Quantité / Qty", F.QUANTITY),
        ("Date d'exécution / Execution Date", F.TRANSACTION_DATE),
        ("Devise / Currency", F.CURRENCY),
    ],
)
def test_match_label_bilingual_combined(label, field):
    assert match_label(label) is field


@pytest.mark.parametrize("label", ["Sharpe Ratio", "Random Gibberish", "", None, "xyz123"])
def test_match_label_unknown_returns_none(label):
    assert match_label(label) is None


def test_no_alias_collisions_on_high_value_fields():
    """Each critical field's own labels must resolve back to that field — i.e.
    no other field silently shadowed them in the reverse index."""
    critical = [
        F.TRANSACTION_DATE,
        F.ACTION,
        F.TICKER,
        F.QUANTITY,
        F.PRICE,
        F.NET_AMOUNT,
        F.COMMISSION,
        F.CURRENCY,
        F.ACCOUNT,
    ]
    for fld in critical:
        for label in CANONICAL_ALIASES[fld]:
            assert match_label(label) is fld, (
                f"label {label!r} for {fld} resolved to {match_label(label)}"
            )
