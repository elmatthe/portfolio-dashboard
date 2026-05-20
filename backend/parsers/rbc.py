"""RBC Direct Investing — CSV (and PDF in Step 6).

Quirks:
- 4-line metadata header block before the column row (RBC branding, account,
  period, blank line).
- Carries in-file FX columns (`Exchange Rate`, `Net CAD Equivalent`) — those
  take priority over FXService per §3.2.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import ClassVar

import pandas as pd

from backend.fx import get_fx_service
from backend.models import Transaction
from backend.parsers._common import (
    compute_hash,
    guess_account_type,
    guess_currency,
    guess_exchange,
    normalize_action,
    parse_date,
    safe_float,
    safe_str,
)
from backend.parsers.base import BaseParser
from backend.parsers.registry import _register

logger = logging.getLogger(__name__)


@_register
class RBCParser(BaseParser):
    BROKER_NAME: ClassVar[str] = "RBC Direct Investing"
    BROKER_KEY: ClassVar[str] = "rbc"
    SUPPORTED_FORMATS: ClassVar[list[str]] = ["csv", "pdf"]

    @classmethod
    def detect(cls, file_path: str | Path, content_sample: str) -> float:
        ext = Path(file_path).suffix.lower()
        s = content_sample.lower()
        if ext == ".csv":
            if "rbc direct investing" in s:
                return 0.95
            if "settlement date" in s and "net cad equivalent" in s:
                return 0.7
        if ext == ".pdf":
            try:
                import pdfplumber
                with pdfplumber.open(file_path) as pdf:
                    if pdf.pages:
                        text = (pdf.pages[0].extract_text() or "").lower()
                        if "rbc direct investing" in text:
                            return 0.95
                        if "rbc" in text and "transaction" in text:
                            return 0.6
            except Exception:
                return 0.0
        return 0.0

    def parse(self, file_path: str | Path) -> list[Transaction]:
        path = Path(file_path)
        return _parse_rbc_csv(path) if path.suffix.lower() == ".csv" else _parse_rbc_pdf(path)


def _parse_rbc_csv(path: Path) -> list[Transaction]:
    text = path.read_text(encoding="utf-8", errors="replace")
    # Extract account number from the 2nd line for stable hashing.
    account_number = "rbc"
    for line in text.splitlines()[:4]:
        m = re.search(r"Account:\s*([\w-]+)", line)
        if m:
            account_number = m.group(1)
            break
    # Find the column header — first row containing "Settlement Date" and "Currency".
    header_idx = _find_csv_header_row(text, must_contain=("Settlement Date", "Currency"))
    if header_idx is None:
        logger.warning("RBC parser: no header row found in %s", path)
        return []
    df = pd.read_csv(path, skiprows=header_idx)
    return _rows_to_transactions(df, account_number, broker="rbc", default_currency="CAD")


_MONTH_ABBR = {"Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"}
_MONTH_NUM = {m: i + 1 for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}


def _parse_rbc_pdf(path: Path) -> list[Transaction]:
    """Extract transactions from the RBC Direct Investing branded PDF.

    The test PDF has overlapping column cells geometrically — characters from
    adjacent columns share x-coordinates. We bypass geometric reconstruction
    by reading the PDF content stream (use_text_flow=True), which preserves
    column order even when positions overlap. Each data row's structure:

        month  day  year  action  [symbol/name tokens]  qty  price  ccy
        gross  comm  net  fx  cad_net  acct

    The trailing 9 columns have known types, so we parse right-to-left.
    """
    try:
        import pdfplumber
    except ImportError:
        logger.warning("pdfplumber required for RBC PDF parsing")
        return []

    from datetime import date as _date

    from backend.fx import get_fx_service
    from backend.parsers._common import compute_hash as _hash, guess_account_type as _acct_type, guess_currency as _ccy, guess_exchange as _exch
    fx_service = get_fx_service()

    # Try to extract the account number from the PDF text.
    account_number = "rbc"
    rows_data: list[list[str]] = []
    with pdfplumber.open(path) as pdf:
        # Account header text (first 200 chars of page 1)
        text_p1 = pdf.pages[0].extract_text() or ""
        m = re.search(r"Account:\s*([\w-]+)", text_p1)
        if m:
            account_number = m.group(1)
        for page in pdf.pages:
            words = page.extract_words(x_tolerance=1.0, y_tolerance=2.0, use_text_flow=True)
            if not words:
                continue
            # Group consecutive words by y-band; a band change starts a new row.
            current_row: list[str] = []
            current_y: float | None = None
            for w in words:
                y = round(w["top"] / 2) * 2
                if current_y is None:
                    current_y = y
                if y != current_y:
                    if current_row:
                        rows_data.append(current_row)
                    current_row = []
                    current_y = y
                current_row.append(w["text"])
            if current_row:
                rows_data.append(current_row)

    out: list[Transaction] = []
    for tokens in rows_data:
        if len(tokens) < 13 or tokens[0] not in _MONTH_ABBR:
            continue
        try:
            month = _MONTH_NUM[tokens[0]]
            day = int(tokens[1])
            year = int(tokens[2])
            trade_date = _date(year, month, day)
        except (ValueError, KeyError):
            continue
        if len(tokens) < 13:
            continue
        action_raw = tokens[3]
        action = {"Buy": "BUY", "Sell": "SELL", "Dividend": "DIVIDEND"}.get(action_raw, "OTHER")
        # Right-to-left positional decode of the 9 trailing typed columns.
        try:
            account_type_label = tokens[-1]
            cad_net = safe_float(tokens[-2])
            fx_rate = safe_float(tokens[-3])
            net = safe_float(tokens[-4])
            commission = safe_float(tokens[-5])
            gross = safe_float(tokens[-6])
            currency = _ccy(tokens[-7], default="CAD")
            price = safe_float(tokens[-8])
            quantity = safe_float(tokens[-9])
        except (IndexError, ValueError):
            continue
        # Symbol + name lives between tokens[4] and tokens[-9].
        name_tokens = tokens[4:-9]
        raw_symbol = None
        description_parts: list[str] = []
        if name_tokens:
            first = name_tokens[0]
            m = re.match(r"^[A-Z0-9.]+", first)
            if m:
                raw_symbol = m.group(0)
                rest_first = first[m.end():].strip()
                if rest_first:
                    description_parts.append(rest_first)
            else:
                raw_symbol = first
            description_parts.extend(name_tokens[1:])
        description = " ".join(description_parts).strip()

        account_type = _acct_type(account_type_label, default="Non-Registered")
        # Buys cost cash — re-sign net + cad_net.
        if action == "BUY" and net > 0:
            net = -net
        if action == "BUY" and cad_net > 0:
            cad_net = -cad_net

        full_account = f"{account_number}-{account_type}"
        h = _hash(
            transaction_date=trade_date,
            action=action,
            raw_symbol=raw_symbol,
            quantity=quantity,
            net_amount=net,
            account_number=full_account,
        )
        out.append(
            Transaction(
                hash=h,
                broker="rbc",
                transaction_date=trade_date,
                action=action,
                raw_symbol=raw_symbol,
                description=description,
                quantity=quantity,
                price=price,
                gross_amount=gross,
                commission=commission,
                net_amount=net,
                currency=currency,
                account_number=full_account,
                account_type=account_type,
                fx_rate_to_cad=fx_rate or fx_service.rate_to_cad(currency, trade_date),
                net_cad=cad_net or round(net * (fx_rate or 1.0), 2),
                exchange=_exch(raw_symbol, currency),
            )
        )
    return out


# ---- shared CSV row converter (RBC + CIBC + TD + NB share most columns) ----

_COL_ALIASES: dict[str, list[str]] = {
    # Order matters: more-specific trade-date aliases win over generic
    # "settlement date" (which appears as a secondary column on Scotia + TD PDF).
    # Settlement date is intentionally LAST so brokers that only carry a
    # settlement column (e.g. RBC CSV) still match.
    "date": ["trade date", "transaction date", "execution date", "trans. date", "value date", "run date", "date d'exécution / execution date", "date", "settlement date"],
    "action": ["activity", "transaction type", "type", "action", "order type", "type d'opération / transaction type"],
    "symbol": ["symbol", "security", "ticker", "ticker symbol", "titre / symbol"],
    "description": ["description", "security description", "company name"],
    "quantity": ["quantity", "shares/units", "units", "no. of shares", "quantité / qty"],
    "price": ["price", "trade price", "price per share", "market price", "unit price", "price ($)", "prix / price"],
    "currency": ["currency", "traded currency", "ccy", "devise / currency"],
    "gross": ["gross amount", "trade amount", "gross", "amount ($)", "gross proceeds", "montant brut / gross"],
    "commission": ["commission", "commission & fees", "fees & commissions", "total charges", "comm.", "commission ($)"],
    "net": ["net amount", "net settlement", "net", "net transaction value", "net proceeds", "montant net / net"],
    "fx": ["exchange rate", "fx rate", "exch rate", "exchange rate to cad", "taux de change / fx rate"],
    "cad_eq": ["net cad equivalent", "cad equivalent", "equivalent cad", "cad net", "book value cad", "équivalent cad / cad equiv"],
    "account_type": ["account type", "registered account", "account", "type de compte / account type"],
    "settlement": ["settlement date"],
    "reference": ["order id", "confirmation", "reference"],
}


def _pick_col(columns: list[str], aliases: list[str]) -> str | None:
    """Return the actual column name (case-insensitive) matching any alias."""
    lower = {c.strip().lower(): c for c in columns}
    for a in aliases:
        if a in lower:
            return lower[a]
    return None


def _rows_to_transactions(
    df: pd.DataFrame,
    account_number_prefix: str,
    broker: str,
    default_currency: str = "CAD",
    *,
    prefer_dmy: bool = False,
    force_fx_from_service: bool = False,
) -> list[Transaction]:
    """Generic row → Transaction converter for the column-aligned brokers."""
    if df.empty:
        return []
    cols = list(df.columns)
    col_date = _pick_col(cols, _COL_ALIASES["date"])
    col_action = _pick_col(cols, _COL_ALIASES["action"])
    col_symbol = _pick_col(cols, _COL_ALIASES["symbol"])
    col_desc = _pick_col(cols, _COL_ALIASES["description"])
    col_qty = _pick_col(cols, _COL_ALIASES["quantity"])
    col_price = _pick_col(cols, _COL_ALIASES["price"])
    col_currency = _pick_col(cols, _COL_ALIASES["currency"])
    col_gross = _pick_col(cols, _COL_ALIASES["gross"])
    col_comm = _pick_col(cols, _COL_ALIASES["commission"])
    col_net = _pick_col(cols, _COL_ALIASES["net"])
    col_fx = _pick_col(cols, _COL_ALIASES["fx"])
    col_cad = _pick_col(cols, _COL_ALIASES["cad_eq"])
    col_acct = _pick_col(cols, _COL_ALIASES["account_type"])
    col_settle = _pick_col(cols, _COL_ALIASES["settlement"])
    col_ref = _pick_col(cols, _COL_ALIASES["reference"])

    fx_service = get_fx_service()
    out: list[Transaction] = []
    for _, row in df.iterrows():
        trade_date = parse_date(row.get(col_date) if col_date else None, prefer_dmy=prefer_dmy)
        if trade_date is None:
            continue
        symbol = safe_str(row.get(col_symbol)) if col_symbol else None
        description = (safe_str(row.get(col_desc)) if col_desc else "") or ""
        quantity = safe_float(row.get(col_qty)) if col_qty else 0.0
        price = safe_float(row.get(col_price)) if col_price else 0.0
        currency = guess_currency(row.get(col_currency) if col_currency else None, default=default_currency)
        gross = safe_float(row.get(col_gross)) if col_gross else 0.0
        commission = safe_float(row.get(col_comm)) if col_comm else 0.0
        net = safe_float(row.get(col_net)) if col_net else gross

        raw_action = safe_str(row.get(col_action)) if col_action else None
        action = normalize_action(raw_action, quantity=quantity, net=net)
        # Buys cost cash (net negative); preserve that sign convention for the hash.
        if action == "BUY" and net > 0:
            net = -net
        if action == "WITHDRAWAL" and net > 0:
            net = -net
        if action == "FEE" and net > 0:
            net = -net

        account_label = safe_str(row.get(col_acct)) if col_acct else None
        account_type = guess_account_type(account_label, default="Non-Registered")
        account_number = f"{account_number_prefix}-{account_type}"

        # FX: prefer in-file, fall back to service
        if col_fx and not force_fx_from_service:
            fx_rate = safe_float(row.get(col_fx)) or None
        else:
            fx_rate = None
        if not fx_rate:
            fx_rate = fx_service.rate_to_cad(currency, trade_date)
        # CAD equivalent: prefer in-file, otherwise compute
        if col_cad:
            cad_val = safe_float(row.get(col_cad)) or None
        else:
            cad_val = None
        if cad_val is None:
            cad_val = round(net * fx_rate, 2)
        else:
            # File's CAD equivalent stays unsigned; re-sign to match `net`.
            if (net < 0 and cad_val > 0) or (net > 0 and cad_val < 0):
                cad_val = -cad_val

        settlement = parse_date(row.get(col_settle) if col_settle else None, prefer_dmy=prefer_dmy)
        reference_id = safe_str(row.get(col_ref)) if col_ref else None

        h = compute_hash(
            transaction_date=trade_date,
            action=action,
            raw_symbol=symbol,
            quantity=quantity,
            net_amount=net,
            account_number=account_number,
        )
        out.append(
            Transaction(
                hash=h,
                broker=broker,
                transaction_date=trade_date,
                settlement_date=settlement,
                action=action,
                raw_symbol=symbol,
                description=description,
                quantity=quantity,
                price=price,
                gross_amount=gross,
                commission=commission,
                net_amount=net,
                currency=currency,
                account_number=account_number,
                account_type=account_type,
                fx_rate_to_cad=fx_rate,
                net_cad=cad_val,
                exchange=guess_exchange(symbol, currency),
                reference_id=reference_id,
            )
        )
    return out


def _find_csv_header_row(text: str, must_contain: tuple[str, ...]) -> int | None:
    """Return the line index of the first row whose lower-cased cells contain
    every `must_contain` substring (case-insensitive). Used to skip the
    branded metadata header blocks that RBC/CIBC/BMO/NB/Fidelity all include.
    """
    for i, line in enumerate(text.splitlines()[:50]):
        low = line.lower()
        if all(s.lower() in low for s in must_contain):
            return i
    return None
