"""Bilingual (EN/FR) header alias dictionary for the universal import lane
(Item 4, Step 1).

Maps every `CanonicalField` to the many labels brokers/banks actually print for
it, in English and French. Matching is case-, space-, punctuation- AND
accent-insensitive (`normalize_label` strips accents so "Date d'exécution"
matches "date d execution").

Seeded from the alias set the named parsers already key off
(`backend.parsers.rbc._COL_ALIASES`) plus the §4 synonym list. Values are COPIED
(not imported) so the generic engine stays decoupled from any one named parser.

This module is the deterministic FIRST pass of column classification. Step 3
layers `rapidfuzz` fuzzy matching and value-profiling on top for labels that
don't hit an exact alias here.

Pure data + tiny helpers. No I/O.
"""
from __future__ import annotations

import re
import unicodedata

from backend.import_engine.canonical import CanonicalField

_F = CanonicalField


# --------------------------------------------------------------------------- #
# Normalization                                                                #
# --------------------------------------------------------------------------- #

def normalize_label(label: str | None) -> str:
    """Canonicalize a header label for alias matching.

    Lowercase, strip accents (NFKD → drop combining marks), turn any run of
    non-alphanumeric characters into a single space, and trim. So
    "Date d'exécution / Execution Date" → "date d execution execution date".
    """
    if not label:
        return ""
    s = unicodedata.normalize("NFKD", str(label))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return s.strip()


# --------------------------------------------------------------------------- #
# Alias dictionary                                                             #
# --------------------------------------------------------------------------- #
# Each canonical field lists its label variants in raw human form; they're
# normalized at import time into the reverse index below. Bilingual combined
# headers (e.g. "quantité / qty") are also entered split so either side matches.

CANONICAL_ALIASES: dict[CanonicalField, list[str]] = {
    _F.TRANSACTION_DATE: [
        "date", "trade date", "transaction date", "execution date", "trans date",
        "trans. date", "value date", "run date", "as of date", "activity date",
        "date d'exécution", "date de transaction", "date d'opération", "date de l'opération",
    ],
    _F.SETTLEMENT_DATE: [
        "settlement date", "settle date", "settled", "date de règlement",
    ],
    _F.ACTION: [
        "action", "activity", "activity type", "transaction type", "type",
        "order type", "trans type", "description type",
        "type d'opération", "type de transaction", "opération", "operation",
    ],
    _F.TICKER: [
        "symbol", "ticker", "ticker symbol", "security", "security symbol",
        "security id", "stock", "cusip symbol",
        "symbole", "titre",
    ],
    _F.SECURITY_NAME: [
        "description", "security name", "name", "company name", "security description",
        "investment", "désignation", "description du titre", "nom du titre", "libellé",
    ],
    _F.QUANTITY: [
        "qty", "quantity", "shares", "units", "shares/units", "no. of shares",
        "number of shares", "share quantity",
        "quantité", "parts", "nombre d'actions", "nb d'actions",
    ],
    _F.PRICE: [
        "price", "trade price", "unit price", "price per share", "market price",
        "price ($)", "avg price", "average price", "execution price",
        "prix", "cours", "prix unitaire", "prix par action",
    ],
    _F.GROSS_AMOUNT: [
        # NOTE: deliberately NO bare "amount"/"value" here — those are too generic
        # and §4 maps a lone "amount" to net_amount. Keep only gross-specific labels.
        "gross amount", "gross", "principal", "trade amount", "gross proceeds",
        "book cost", "montant brut", "brut",
    ],
    _F.COMMISSION: [
        "commission", "commissions", "fee", "fees", "comm", "comm.",
        "commission & fees", "fees & commissions", "total charges", "commission/fee",
        "commission ($)", "frais", "frais de courtage", "commission et frais",
    ],
    _F.NET_AMOUNT: [
        "amount", "net amount", "net", "net settlement", "net transaction value",
        "proceeds", "net proceeds", "settlement amount", "total", "total amount",
        "montant net", "montant", "net à payer", "produit net",
    ],
    _F.DEBIT: ["debit", "withdrawal", "money out", "débit", "retrait", "sortie"],
    _F.CREDIT: ["credit", "deposit", "money in", "crédit", "dépôt", "entrée"],
    _F.CURRENCY: [
        "currency", "ccy", "cur", "traded currency", "settlement currency",
        "devise", "monnaie",
    ],
    _F.FX_RATE: [
        "exchange rate", "fx rate", "exch rate", "rate", "exchange rate to cad",
        "fx rate to cad", "taux de change", "taux",
    ],
    _F.ACCOUNT: [
        "account", "account #", "account number", "account no", "acct", "acct #",
        "compte", "n° de compte", "numéro de compte",
    ],
    _F.ACCOUNT_TYPE: [
        "account type", "registered account", "account category", "plan type",
        "type de compte", "catégorie de compte",
    ],
    _F.ISIN: ["isin", "isin code", "international security id", "code isin"],
    _F.EXCHANGE: ["exchange", "market", "mkt", "listing exchange", "bourse", "marché"],
    _F.REFERENCE_ID: [
        "order id", "confirmation", "confirmation number", "reference",
        "reference id", "ref", "ref #", "transaction id", "référence", "n° de référence",
    ],
}


# --------------------------------------------------------------------------- #
# Reverse index + lookup                                                       #
# --------------------------------------------------------------------------- #
# normalized-label -> CanonicalField. Built once at import. If two fields ever
# claim the same normalized label, the FIRST in CANONICAL_ALIASES iteration wins
# and we keep it deterministic (a unit test guards against silent collisions on
# the high-value fields).

def _build_reverse_index() -> dict[str, CanonicalField]:
    index: dict[str, CanonicalField] = {}
    for field_, labels in CANONICAL_ALIASES.items():
        for label in labels:
            norm = normalize_label(label)
            if not norm:
                continue
            # Also index each whitespace-split half of a combined bilingual
            # label so "quantite qty" still matches via its parts is NOT done
            # here (we keep exact normalized labels); split handling lives in
            # match_label() which tries slash-separated halves.
            index.setdefault(norm, field_)
    return index


_REVERSE_INDEX: dict[str, CanonicalField] = _build_reverse_index()


def match_label(label: str | None) -> CanonicalField | None:
    """Exact (normalized) alias match for a single header label.

    Returns the `CanonicalField` for a recognized label, else None. Handles
    bilingual combined headers like "Quantité / Qty" by also trying each
    slash-separated half.
    """
    if not label:
        return None
    norm = normalize_label(label)
    if norm in _REVERSE_INDEX:
        return _REVERSE_INDEX[norm]
    # Try slash-separated halves of a combined bilingual header.
    for part in re.split(r"\s*/\s*", str(label)):
        pnorm = normalize_label(part)
        if pnorm and pnorm in _REVERSE_INDEX:
            return _REVERSE_INDEX[pnorm]
    return None


def known_labels() -> dict[str, CanonicalField]:
    """The full normalized-label → field index (read-only view for Step 3)."""
    return dict(_REVERSE_INDEX)
