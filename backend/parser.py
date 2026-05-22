"""Multi-broker transaction parser.

Auto-detects Questrade (.xlsx) and Wealthsimple (.csv, .pdf) by sniffing the file,
then normalises every row into a `Transaction` with a deterministic SHA-256 `hash`.

The hash uses: transaction_date + action + raw_symbol + quantity + net_amount + account_number.
Re-importing the same file (or an overlapping export) produces zero new transactions.
"""
from __future__ import annotations

import hashlib
import re
import warnings
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from backend.models import AccountType, Action, Broker, Currency, Transaction


# ---------- Detection ----------

@dataclass
class DetectedFormat:
    broker: Broker
    fmt: str  # "xlsx" | "csv" | "pdf"


class UnknownFormatError(Exception):
    """Raised when the file isn't recognized as Questrade or Wealthsimple."""


def detect_broker_and_format(file_path: str | Path) -> DetectedFormat:
    """Sniff the file and return its broker + concrete format.

    Order: extension → magic-byte check on contents. Raises UnknownFormatError if
    we can't recognize it (the API surfaces this as a friendly error to the user).
    """
    p = Path(file_path)
    ext = p.suffix.lower()

    if ext in (".xlsx", ".xlsm"):
        # Questrade is the only xlsx broker we support today. Sanity-check the sheet.
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                xl = pd.ExcelFile(p)
            if any(s.lower() == "activities" for s in xl.sheet_names):
                return DetectedFormat(broker="questrade", fmt="xlsx")
        except Exception:
            pass
        raise UnknownFormatError("This .xlsx doesn't look like a Questrade Activities export.")

    if ext == ".csv":
        # Wealthsimple Activities CSV has Date/Activity/Symbol/Quantity/Price/Amount headers.
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                df = pd.read_csv(p, nrows=5, encoding_errors="replace")
            headers = {c.strip().lower() for c in df.columns}
            required = {"date", "amount"}
            ws_signal = {"activity", "type"} & headers
            if required.issubset(headers) and ws_signal:
                return DetectedFormat(broker="wealthsimple", fmt="csv")
        except Exception:
            pass
        raise UnknownFormatError("This .csv doesn't look like a Wealthsimple Activities export.")

    if ext == ".pdf":
        # Wealthsimple statements identify themselves on the first page.
        try:
            import pdfplumber

            with pdfplumber.open(p) as pdf:
                text = (pdf.pages[0].extract_text() or "").lower() if pdf.pages else ""
            if "wealthsimple" in text:
                return DetectedFormat(broker="wealthsimple", fmt="pdf")
        except ImportError:
            raise UnknownFormatError("PDF support requires pdfplumber.")
        except Exception:
            pass
        raise UnknownFormatError("This PDF doesn't look like a Wealthsimple statement.")

    raise UnknownFormatError(f"Unsupported file extension: {ext}")


# ---------- Public entry point ----------

def parse_file(file_path: str | Path) -> tuple[list[Transaction], DetectedFormat]:
    """Parse a transaction file by routing through the v0.3.0 parser registry.

    The registry handles all 11 brokers + a generic fallback. Questrade and
    Wealthsimple are still wrapped by the same legacy functions below, so
    their hash output is byte-identical to v0.2.0 (regression preserved).

    Raises UnknownFormatError when no parser scores ≥ 0.5 and the generic
    fallback fails too — the API surfaces this as a 400 to the user.
    """
    # Late import: backend.parsers depends on this module's compute_hash, so
    # importing at module top would create a cycle.
    from backend.parsers import parse_with_registry

    result = parse_with_registry(file_path)
    if not result.transactions and result.confidence < 0.5:
        # Last-ditch: try the legacy detector so any pre-v0.3.0 quirks still
        # surface a useful error to the user.
        try:
            fmt = detect_broker_and_format(file_path)
        except UnknownFormatError:
            raise
        raise UnknownFormatError(f"No transactions could be parsed from {Path(file_path).name}")
    return result.transactions, DetectedFormat(broker=result.broker_key, fmt=result.fmt)


# ---------- Questrade ----------

QUESTRADE_ACTION_MAP: dict[str, Action] = {
    "BUY": "BUY",
    "SELL": "SELL",
    "DIV": "DIVIDEND",
    "DEP": "DEPOSIT",
    "CON": "CONTRIBUTION",
    "WDR": "WITHDRAWAL",
    "FEE": "FEE",
    "INT": "INTEREST",
}


QUESTRADE_ACCOUNT_MAP: dict[str, AccountType] = {
    "Individual TFSA": "TFSA",
    "Individual margin": "Margin",
    "Joint margin": "Margin",
    "RRSP": "RRSP",
    "Individual RRSP": "RRSP",
    "RESP": "RESP",
    "Family RESP": "RESP",
}


def parse_questrade_xlsx(file_path: str | Path) -> list[Transaction]:
    """Parse the Activities sheet of a Questrade transaction export."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = pd.read_excel(file_path, sheet_name="Activities")

    # Strip the literal " 12:00:00 AM" off every date string before parsing.
    df["Transaction Date"] = df["Transaction Date"].apply(_parse_questrade_date)
    df["Settlement Date"] = df["Settlement Date"].apply(_parse_questrade_date)

    out: list[Transaction] = []
    for _, row in df.iterrows():
        action = _questrade_action(row)
        raw_symbol = _safe_str(row.get("Symbol"))
        description = _safe_str(row.get("Description")) or ""
        resolved_ticker = normalize_questrade_symbol(raw_symbol, description) if raw_symbol else None
        currency: Currency = "USD" if _safe_str(row.get("Currency")) == "USD" else "CAD"
        account_type = QUESTRADE_ACCOUNT_MAP.get(_safe_str(row.get("Account Type")) or "", "Margin")
        account_number = str(row.get("Account #") or "").strip() or "unknown"
        transaction_date = row["Transaction Date"]
        settlement_date = row["Settlement Date"]
        quantity = _safe_float(row.get("Quantity"))
        price = _safe_float(row.get("Price"))
        gross_amount = _safe_float(row.get("Gross Amount"))
        commission = _safe_float(row.get("Commission"))
        net_amount = _safe_float(row.get("Net Amount"))

        if transaction_date is None or action is None:
            continue

        h = compute_hash(
            transaction_date=transaction_date,
            action=action,
            raw_symbol=raw_symbol,
            quantity=quantity,
            net_amount=net_amount,
            account_number=account_number,
        )

        out.append(
            Transaction(
                hash=h,
                broker="questrade",
                transaction_date=transaction_date,
                settlement_date=settlement_date,
                action=action,
                raw_symbol=raw_symbol,
                resolved_ticker=resolved_ticker,
                description=description,
                quantity=quantity,
                price=price,
                gross_amount=gross_amount,
                commission=commission,
                net_amount=net_amount,
                currency=currency,
                account_number=account_number,
                account_type=account_type,
            )
        )

    return out


def _questrade_action(row: pd.Series) -> Action | None:
    """Pick the canonical action.

    Questrade often leaves Action blank for dividends and sets Activity Type='Dividends'
    instead — we honour that first. As a final fallback for NaN-action rows that don't
    have a recognisable Activity Type, classify by shape:
      - has a symbol + positive net amount  → DIVIDEND
      - no symbol     + positive net amount → DEPOSIT
      - otherwise                           → OTHER
    """
    raw_action = _safe_str(row.get("Action"))
    activity = _safe_str(row.get("Activity Type")) or ""
    activity_lc = activity.lower()

    if raw_action:
        key = raw_action.upper()
        if key in QUESTRADE_ACTION_MAP:
            return QUESTRADE_ACTION_MAP[key]
        if key in ("BUY", "SELL"):
            return key  # type: ignore[return-value]

    if "dividend" in activity_lc:
        return "DIVIDEND"
    if "deposit" in activity_lc:
        return "DEPOSIT"
    if "trade" in activity_lc:
        # Trades with blank action shouldn't happen, but be defensive.
        qty = _safe_float(row.get("Quantity"))
        if qty > 0:
            return "BUY"
        if qty < 0:
            return "SELL"
    if "interest" in activity_lc:
        return "INTEREST"
    if "fee" in activity_lc:
        return "FEE"

    # Final shape-based fallback for genuinely blank rows.
    if not raw_action:
        symbol = _safe_str(row.get("Symbol"))
        net = _safe_float(row.get("Net Amount"))
        if symbol and net > 0:
            return "DIVIDEND"
        if not symbol and net > 0:
            return "DEPOSIT"
    return "OTHER"


# ---------- Symbol normalization ----------

_INTERNAL_ID_RE = re.compile(r"^[A-Z]{1,3}\d{5,}$")


# Hand-mapped descriptions for the most common Questrade internal IDs in the wild.
# Used as a fast path before any yfinance.search() call (which happens in market_data.py).
#
# TODO: this list covers only the top-traded U.S. tickers. Anything outside it
# falls through to `yfinance.search()` (in market_data.py), which the comment in
# `import_file` notes is unreliable for Questrade-internal symbols. A more
# complete description→ticker mapping is available in tsiemens/acb under
# `py/tx-export-convert/symbol_resolver.py` — port that table here when coverage
# becomes a pain point.
_KNOWN_DESCRIPTION_TICKERS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bAPPLE\s+INC\b", re.I), "AAPL"),
    (re.compile(r"\bVANGUARD\s+S&P\s*500\s+ETF\b", re.I), "VOO"),
    (re.compile(r"\bMICROSOFT\b", re.I), "MSFT"),
    (re.compile(r"\bNVIDIA\b", re.I), "NVDA"),
    (re.compile(r"\bAMAZON\b", re.I), "AMZN"),
    (re.compile(r"\bGOOGLE\b|\bALPHABET\b", re.I), "GOOGL"),
    (re.compile(r"\bMETA\s+PLATFORMS\b|\bFACEBOOK\b", re.I), "META"),
    (re.compile(r"\bTESLA\b", re.I), "TSLA"),
]


def normalize_questrade_symbol(raw_symbol: str | None, description: str | None = None) -> str | None:
    """Apply the cascade from the plan. Returns the normalized ticker, or None.

    Cascade:
      1. Ends in .TO → keep
      2. Starts with `.` → strip, append `.TO`
      3. Internal ID pattern → look up by description (or fall back to None for yfinance.search)
      4. Pure alpha 1-5 chars → US ticker, keep as-is
    """
    if not raw_symbol:
        return None
    s = raw_symbol.strip()
    if not s:
        return None

    upper = s.upper()

    if upper.endswith(".TO"):
        return upper
    if upper.startswith("."):
        return f"{upper[1:]}.TO"
    if _INTERNAL_ID_RE.match(upper):
        if description:
            for pat, ticker in _KNOWN_DESCRIPTION_TICKERS:
                if pat.search(description):
                    return ticker
        return None  # market_data.py will yfinance.search() this raw id
    if re.fullmatch(r"[A-Z]{1,5}", upper):
        # Could be a Canadian unsuffixed (VEQT) or a US ticker (VOO).
        # If description mentions Vanguard/BMO/iShares and "ETF", lean Canadian.
        if description:
            d = description.upper()
            if any(canadian in d for canadian in ("BMO MSCI", "VANGUARD ALL-EQUITY")):
                return f"{upper}.TO"
        return upper

    return upper


# ---------- Wealthsimple ----------

WS_ACTION_MAP: dict[str, Action] = {
    "buy": "BUY",
    "sell": "SELL",
    "dividend": "DIVIDEND",
    "dividends": "DIVIDEND",
    "deposit": "DEPOSIT",
    "transfer in": "DEPOSIT",
    "internal transfer": "DEPOSIT",
    "withdrawal": "WITHDRAWAL",
    "transfer out": "WITHDRAWAL",
    "contribution": "CONTRIBUTION",
    "interest": "INTEREST",
    "fee": "FEE",
    "fees": "FEE",
    "stock split": "SPLIT",
    "split": "SPLIT",
}


WS_ACCOUNT_MAP: dict[str, AccountType] = {
    "tfsa": "TFSA",
    "rrsp": "RRSP",
    "personal": "Margin",
    "non-registered": "Margin",
    "margin": "Margin",
    "crypto": "Crypto",
    "resp": "RESP",
}


def parse_wealthsimple_csv(file_path: str | Path) -> list[Transaction]:
    """Read a Wealthsimple Activities CSV into normalised Transaction objects."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = pd.read_csv(file_path, encoding_errors="replace")
    return _parse_wealthsimple_rows(df.to_dict(orient="records"))


def parse_wealthsimple_pdf(file_path: str | Path) -> list[Transaction]:
    """Best-effort extraction of Wealthsimple statement-PDF transaction tables via pdfplumber."""
    try:
        import pdfplumber
    except ImportError as e:
        raise UnknownFormatError("pdfplumber required for PDF parsing") from e

    records: list[dict[str, Any]] = []
    header: list[str] | None = None
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                if not table:
                    continue
                first = [str(c or "").strip().lower() for c in table[0]]
                # Treat as header row if it contains a "date" cell.
                if "date" in first:
                    header = first
                    data_rows = table[1:]
                else:
                    data_rows = table
                if header is None:
                    continue
                for row in data_rows:
                    if not any(row):
                        continue
                    records.append({header[i]: row[i] for i in range(min(len(header), len(row)))})

    return _parse_wealthsimple_rows(records)


def _parse_wealthsimple_rows(records: Iterable[dict[str, Any]]) -> list[Transaction]:
    """Internal row normaliser shared by the CSV and PDF Wealthsimple parsers."""
    out: list[Transaction] = []
    for rec in records:
        norm = {(k or "").strip().lower(): v for k, v in rec.items()}
        transaction_date = _parse_iso_date(norm.get("date"))
        if transaction_date is None:
            continue
        action_raw = (_safe_str(norm.get("activity")) or _safe_str(norm.get("type")) or "").lower()
        action = WS_ACTION_MAP.get(action_raw, "OTHER")
        raw_symbol = _safe_str(norm.get("symbol"))
        description = _safe_str(norm.get("description")) or ""
        quantity = _safe_float(norm.get("quantity"))
        price = _safe_float(norm.get("price"))
        net_amount = _parse_ws_amount(norm.get("amount"))
        currency: Currency = "USD" if (_safe_str(norm.get("currency")) or "").upper() == "USD" else "CAD"
        # Wealthsimple's Account column carries values like "TFSA-9901",
        # "Personal-4402", "RRSP-1234", or just "TFSA". Match by the prefix
        # before any separator so the account-number suffix doesn't break
        # the type detection.
        account_raw = (
            _safe_str(norm.get("account type")) or _safe_str(norm.get("account")) or ""
        ).lower()
        # Split off any "-1234" or " 9901" suffix.
        prefix = account_raw.split("-", 1)[0].split(" ", 1)[0].strip()
        account_type = WS_ACCOUNT_MAP.get(prefix, WS_ACCOUNT_MAP.get(account_raw, "Margin"))
        account_number = (
            _safe_str(norm.get("account #"))
            or _safe_str(norm.get("account id"))
            or _safe_str(norm.get("account"))
            or "wealthsimple"
        )

        # Wealthsimple symbols can be raw US tickers, "VEQT" (CAD ETF), or empty.
        resolved_ticker = normalize_wealthsimple_symbol(raw_symbol, description)

        h = compute_hash(
            transaction_date=transaction_date,
            action=action,
            raw_symbol=raw_symbol,
            quantity=quantity,
            net_amount=net_amount,
            account_number=account_number,
        )
        out.append(
            Transaction(
                hash=h,
                broker="wealthsimple",
                transaction_date=transaction_date,
                action=action,
                raw_symbol=raw_symbol,
                resolved_ticker=resolved_ticker,
                description=description,
                quantity=quantity,
                price=price,
                net_amount=net_amount,
                currency=currency,
                account_number=account_number,
                account_type=account_type,
            )
        )
    return out


def normalize_wealthsimple_symbol(raw_symbol: str | None, description: str | None) -> str | None:
    """Map a Wealthsimple-formatted ticker to its yfinance-resolvable form."""
    if not raw_symbol:
        return None
    s = raw_symbol.strip().upper()
    if not s:
        return None
    if s.endswith(".TO") or s.endswith(".NE") or s.endswith(".V") or s.endswith(".CN"):
        return s
    # Wealthsimple sometimes writes "VEQT.TO" and sometimes "VEQT" — same heuristic as Questrade.
    return normalize_questrade_symbol(s, description)


# ---------- Utilities ----------

def compute_hash(
    *,
    transaction_date: date,
    action: str,
    raw_symbol: str | None,
    quantity: float,
    net_amount: float,
    account_number: str,
) -> str:
    """Stable identity. Two rows with the same hash are the same transaction.

    Round floats so trivial precision noise (e.g. 0.0 vs 0.00000) doesn't break dedup.
    """
    parts = [
        transaction_date.isoformat(),
        action.upper(),
        (raw_symbol or "").upper(),
        f"{round(quantity, 6):.6f}",
        f"{round(net_amount, 4):.4f}",
        account_number,
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _parse_questrade_date(value: Any) -> date | None:
    """Questrade dates arrive as either '2025-01-14 12:00:00 AM' strings or real datetimes."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s or s.lower() == "nan":
        return None
    # Drop the trailing " 12:00:00 AM"-ish portion if present.
    s = re.sub(r"\s+\d{1,2}:\d{2}:\d{2}\s*(AM|PM)?$", "", s, flags=re.I)
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    try:
        return pd.to_datetime(s).date()
    except Exception:
        return None


def _parse_iso_date(value: Any) -> date | None:
    """Parse YYYY-MM-DD (and other common forms) into a datetime.date. Returns None on failure."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s or s.lower() == "nan":
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    try:
        return pd.to_datetime(s).date()
    except Exception:
        return None


def _safe_str(v: Any) -> str | None:
    """Return a non-empty string or None for NaN/blank inputs."""
    if v is None:
        return None
    if isinstance(v, float) and v != v:  # NaN
        return None
    s = str(v).strip()
    if not s or s.lower() == "nan":
        return None
    return s


def _safe_float(v: Any) -> float:
    """Float parser that handles currency strings ($1,234.56) and parenthesised negatives."""
    if v is None:
        return 0.0
    if isinstance(v, float) and v != v:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        # Strip currency, commas, parens (for negative amounts).
        s = str(v).strip()
        if not s:
            return 0.0
        neg = s.startswith("(") and s.endswith(")")
        s = s.replace("(", "").replace(")", "").replace("$", "").replace(",", "")
        try:
            f = float(s)
            return -f if neg else f
        except ValueError:
            return 0.0


def _parse_ws_amount(v: Any) -> float:
    """Wealthsimple amounts can use '(123.45)' for negatives and embedded currency symbols."""
    return _safe_float(v)
