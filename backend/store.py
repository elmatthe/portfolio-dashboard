"""Persistence layer — the ONLY module that touches the database directly.

All other modules call into here; this lets us swap the storage implementation
later without ripping through the codebase.

Dedup contract: `upsert_transactions` is idempotent. Re-uploading the same file
inserts zero rows. The hash column has a UNIQUE constraint and we use
SQLite's INSERT OR IGNORE so collisions are skipped, not raised.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd
from sqlalchemy import delete, insert, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from backend import db
from backend.models import (
    AppSettings,
    ImportInfo,
    ResolvedTicker,
    Transaction,
)


@dataclass
class UpsertResult:
    inserted: int
    skipped_duplicates: int
    total_in_db: int


# ---------- transactions ----------

def upsert_transactions(transactions: list[Transaction]) -> UpsertResult:
    """Insert each transaction; silently skip rows whose hash already exists.

    Returns counts that the API surfaces in `ImportResult`.
    """
    engine = db.get_engine()
    if not transactions:
        with engine.connect() as conn:
            total = conn.execute(select(db.transactions).with_only_columns(db.transactions.c.id)).fetchall()
        return UpsertResult(inserted=0, skipped_duplicates=0, total_in_db=len(total))

    now = datetime.utcnow()
    rows = [
        {
            "hash": t.hash,
            "broker": t.broker,
            "transaction_date": t.transaction_date.isoformat(),
            "settlement_date": t.settlement_date.isoformat() if t.settlement_date else None,
            "action": t.action,
            "raw_symbol": t.raw_symbol,
            "resolved_ticker": t.resolved_ticker,
            "description": t.description or "",
            "quantity": float(t.quantity),
            "price": float(t.price),
            "gross_amount": float(t.gross_amount),
            "commission": float(t.commission),
            "net_amount": float(t.net_amount),
            "currency": t.currency,
            "account_number": t.account_number,
            "account_type": t.account_type,
            "imported_at": now,
            "fx_rate_to_cad": float(t.fx_rate_to_cad) if t.fx_rate_to_cad is not None else None,
            "net_cad": float(t.net_cad) if t.net_cad is not None else None,
            "isin": t.isin,
            "exchange": t.exchange,
            "reference_id": t.reference_id,
        }
        for t in transactions
    ]

    inserted = 0
    skipped = 0
    with engine.begin() as conn:
        for r in rows:
            stmt = sqlite_insert(db.transactions).values(**r).prefix_with("OR IGNORE")
            res = conn.execute(stmt)
            if res.rowcount == 1:
                inserted += 1
            else:
                skipped += 1

        total = conn.execute(select(db.transactions.c.id)).fetchall()

    return UpsertResult(inserted=inserted, skipped_duplicates=skipped, total_in_db=len(total))


def get_all_transactions() -> list[Transaction]:
    """All transactions, chronological — the canonical input to ACB/portfolio."""
    engine = db.get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            select(db.transactions).order_by(db.transactions.c.transaction_date.asc(), db.transactions.c.id.asc())
        ).mappings().all()
    return [_row_to_transaction(r) for r in rows]


def has_any_transactions() -> bool:
    """True if the active profile has at least one transaction in the DB."""
    engine = db.get_engine()
    with engine.connect() as conn:
        row = conn.execute(select(db.transactions.c.id).limit(1)).first()
    return row is not None


def transaction_count() -> int:
    """Total transactions in the active profile's DB."""
    engine = db.get_engine()
    with engine.connect() as conn:
        rows = conn.execute(select(db.transactions.c.id)).fetchall()
    return len(rows)


def _row_to_transaction(r: dict[str, Any]) -> Transaction:
    """Hydrate a Transaction Pydantic model from a SQLAlchemy row mapping."""
    return Transaction(
        hash=r["hash"],
        broker=r["broker"],
        transaction_date=datetime.fromisoformat(r["transaction_date"]).date()
        if r["transaction_date"]
        else None,
        settlement_date=datetime.fromisoformat(r["settlement_date"]).date()
        if r["settlement_date"]
        else None,
        action=r["action"],
        raw_symbol=r["raw_symbol"],
        resolved_ticker=r["resolved_ticker"],
        description=r["description"] or "",
        quantity=r["quantity"],
        price=r["price"],
        gross_amount=r["gross_amount"],
        commission=r["commission"],
        net_amount=r["net_amount"],
        currency=r["currency"],
        account_number=r["account_number"],
        account_type=r["account_type"],
        fx_rate_to_cad=r.get("fx_rate_to_cad"),
        net_cad=r.get("net_cad"),
        isin=r.get("isin"),
        exchange=r.get("exchange"),
        reference_id=r.get("reference_id"),
    )


def update_resolved_ticker(raw_symbol: str, resolved_ticker: str) -> None:
    """Propagate a newly-resolved ticker back onto every transaction row that used it."""
    engine = db.get_engine()
    with engine.begin() as conn:
        conn.execute(
            update(db.transactions)
            .where(db.transactions.c.raw_symbol == raw_symbol)
            .values(resolved_ticker=resolved_ticker)
        )


# ---------- ticker map ----------

def get_ticker_map() -> dict[str, ResolvedTicker]:
    """Cached raw-symbol → resolved-ticker map, used to avoid re-running yfinance.search."""
    engine = db.get_engine()
    with engine.connect() as conn:
        rows = conn.execute(select(db.ticker_map)).mappings().all()
    return {
        r["raw_symbol"]: ResolvedTicker(
            raw_symbol=r["raw_symbol"],
            resolved_ticker=r["resolved_ticker"],
            security_name=r["security_name"],
            exchange=r["exchange"],
            currency=r["currency"],
            resolved_from=r["resolved_from"] or "pattern",
            status=r["status"] or "resolved",
        )
        for r in rows
    }


def save_ticker_resolution(resolved: ResolvedTicker) -> None:
    """Persist a (raw, resolved) ticker mapping so future imports don't repeat the resolution work."""
    engine = db.get_engine()
    payload = {
        "raw_symbol": resolved.raw_symbol,
        "resolved_ticker": resolved.resolved_ticker,
        "security_name": resolved.security_name,
        "exchange": resolved.exchange,
        "currency": resolved.currency,
        "resolved_from": resolved.resolved_from,
        "status": resolved.status,
        "resolved_at": datetime.utcnow(),
    }
    with engine.begin() as conn:
        stmt = sqlite_insert(db.ticker_map).values(**payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=[db.ticker_map.c.raw_symbol],
            set_={k: v for k, v in payload.items() if k != "raw_symbol"},
        )
        conn.execute(stmt)


def get_unresolved_raw_symbols() -> list[str]:
    """Raw symbols flagged unresolved for manual UI mapping."""
    engine = db.get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            select(db.ticker_map.c.raw_symbol).where(db.ticker_map.c.status == "unresolved")
        ).fetchall()
    return [r[0] for r in rows]


# ---------- prices ----------

def save_current_price(ticker: str, price: float, currency: str) -> None:
    """Upsert the latest price for a ticker into the price_cache table."""
    engine = db.get_engine()
    payload = {"ticker": ticker, "price": float(price), "currency": currency, "fetched_at": datetime.utcnow()}
    with engine.begin() as conn:
        stmt = sqlite_insert(db.price_cache).values(**payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=[db.price_cache.c.ticker],
            set_={k: v for k, v in payload.items() if k != "ticker"},
        )
        conn.execute(stmt)


def get_cached_price(ticker: str, max_age_minutes: int | None = None) -> dict[str, Any] | None:
    """Return {price, currency, fetched_at, age_minutes, stale} or None."""
    engine = db.get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            select(db.price_cache).where(db.price_cache.c.ticker == ticker)
        ).mappings().first()
    if row is None:
        return None
    age = (datetime.utcnow() - row["fetched_at"]).total_seconds() / 60
    stale = max_age_minutes is not None and age > max_age_minutes
    return {
        "ticker": row["ticker"],
        "price": row["price"],
        "currency": row["currency"],
        "fetched_at": row["fetched_at"],
        "age_minutes": age,
        "stale": stale,
    }


def save_price_history(ticker: str, df: pd.DataFrame) -> int:
    """Bulk upsert OHLCV rows. df index is the date; columns include Close (case-insensitive)."""
    if df is None or df.empty:
        return 0
    engine = db.get_engine()
    cols = {c.lower(): c for c in df.columns}
    inserted = 0
    with engine.begin() as conn:
        for idx, row in df.iterrows():
            d = idx
            if hasattr(d, "date"):
                d = d.date()
            date_str = d.isoformat()
            payload = {
                "ticker": ticker,
                "date": date_str,
                "open": _safe_float(row.get(cols.get("open", "Open"))),
                "high": _safe_float(row.get(cols.get("high", "High"))),
                "low": _safe_float(row.get(cols.get("low", "Low"))),
                "close": _safe_float(row.get(cols.get("close", "Close"))),
                "volume": _safe_float(row.get(cols.get("volume", "Volume"))),
            }
            if payload["close"] is None:
                continue
            stmt = sqlite_insert(db.price_history).values(**payload).prefix_with("OR REPLACE")
            res = conn.execute(stmt)
            if res.rowcount >= 1:
                inserted += 1
    return inserted


def _safe_float(v) -> float | None:
    """Inner float coercion used while bulk-inserting OHLCV rows."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    # NaN check
    if f != f:
        return None
    return f


def get_price_history(ticker: str, start: str | None = None) -> pd.DataFrame:
    """Return the locally cached OHLCV DataFrame for a ticker, optionally trimmed to a start date."""
    engine = db.get_engine()
    stmt = select(db.price_history).where(db.price_history.c.ticker == ticker)
    if start:
        stmt = stmt.where(db.price_history.c.date >= start)
    stmt = stmt.order_by(db.price_history.c.date.asc())
    with engine.connect() as conn:
        rows = conn.execute(stmt).mappings().all()
    if not rows:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    return df[["open", "high", "low", "close", "volume"]]


# ---------- exchange rates ----------

def save_exchange_rate(pair: str, rate: float, rate_date: str | None = None) -> None:
    """Persist a forex rate (e.g. USDCAD) — either the live rate or a historical one keyed by date."""
    engine = db.get_engine()
    payload = {
        "pair": pair,
        "rate": float(rate),
        "rate_date": rate_date,
        "fetched_at": datetime.utcnow(),
    }
    with engine.begin() as conn:
        stmt = sqlite_insert(db.exchange_rates).values(**payload).prefix_with("OR REPLACE")
        conn.execute(stmt)


def get_exchange_rate(
    pair: str, max_age_minutes: int | None = None, rate_date: str | None = None
) -> dict[str, Any] | None:
    """Look up a cached forex rate, returning age/stale info."""
    engine = db.get_engine()
    stmt = select(db.exchange_rates).where(db.exchange_rates.c.pair == pair)
    if rate_date is not None:
        stmt = stmt.where(db.exchange_rates.c.rate_date == rate_date)
    else:
        stmt = stmt.where(db.exchange_rates.c.rate_date.is_(None))
    stmt = stmt.order_by(db.exchange_rates.c.fetched_at.desc()).limit(1)
    with engine.connect() as conn:
        row = conn.execute(stmt).mappings().first()
    if row is None:
        return None
    age = (datetime.utcnow() - row["fetched_at"]).total_seconds() / 60
    stale = max_age_minutes is not None and age > max_age_minutes
    return {
        "pair": row["pair"],
        "rate": row["rate"],
        "rate_date": row["rate_date"],
        "fetched_at": row["fetched_at"],
        "age_minutes": age,
        "stale": stale,
    }


# ---------- app_state ----------

def set_state(key: str, value: str | None) -> None:
    """Upsert a key/value pair in the app_state table."""
    engine = db.get_engine()
    with engine.begin() as conn:
        stmt = sqlite_insert(db.app_state).values(key=key, value=value)
        stmt = stmt.on_conflict_do_update(index_elements=[db.app_state.c.key], set_={"value": value})
        conn.execute(stmt)


def get_state(key: str) -> str | None:
    """Read a key from the app_state table. Returns None if missing."""
    engine = db.get_engine()
    with engine.connect() as conn:
        row = conn.execute(select(db.app_state.c.value).where(db.app_state.c.key == key)).first()
    return row[0] if row else None


def get_last_import_info() -> ImportInfo:
    """Compose the ImportInfo struct shown on the dashboard banner."""
    filename = get_state("last_import_filename")
    timestamp_str = get_state("last_import_at")
    timestamp = datetime.fromisoformat(timestamp_str) if timestamp_str else None
    return ImportInfo(
        filename=filename,
        timestamp=timestamp,
        transaction_count=transaction_count(),
    )


def get_settings() -> AppSettings:
    """Read all settings into an AppSettings model with defaults for missing keys."""
    def _int(key: str) -> int | None:
        """Read an integer setting from app_state; returns None if unset."""
        v = get_state(key)
        return int(v) if v and v.lstrip("-").isdigit() else None

    return AppSettings(
        preferred_currency=get_state("preferred_currency") or "CAD",  # type: ignore[arg-type]
        default_chart_frequency=get_state("default_chart_frequency") or "weekly",  # type: ignore[arg-type]
        risk_free_rate=float(get_state("risk_free_rate") or "0.0375"),
        marginal_tax_rate=float(get_state("marginal_tax_rate") or "0.26"),
        tax_province=get_state("tax_province") or "ON",
        tfsa_birth_year=_int("tfsa_birth_year"),
        tfsa_resident_since=_int("tfsa_resident_since"),
        default_period=get_state("default_period") or "all",  # type: ignore[arg-type]
        default_currency_view=get_state("default_currency_view") or "combined_cad",  # type: ignore[arg-type]
        color_theme=get_state("color_theme") or "dark",  # type: ignore[arg-type]
        price_refresh_interval_min=int(get_state("price_refresh_interval_min") or "30"),
    )


def save_settings(s: AppSettings) -> None:
    """Persist every field of an AppSettings model into app_state."""
    set_state("preferred_currency", s.preferred_currency)
    set_state("default_chart_frequency", s.default_chart_frequency)
    set_state("risk_free_rate", str(s.risk_free_rate))
    set_state("marginal_tax_rate", str(s.marginal_tax_rate))
    set_state("tax_province", s.tax_province)
    set_state("tfsa_birth_year", str(s.tfsa_birth_year) if s.tfsa_birth_year is not None else None)
    set_state("tfsa_resident_since", str(s.tfsa_resident_since) if s.tfsa_resident_since is not None else None)
    set_state("default_period", s.default_period)
    set_state("default_currency_view", s.default_currency_view)
    set_state("color_theme", s.color_theme)
    set_state("price_refresh_interval_min", str(s.price_refresh_interval_min))


# ---------- destructive (tests / "reset" feature) ----------

def wipe_all_data() -> None:
    """Used by tests and a future user-facing 'reset everything' button."""
    engine = db.get_engine()
    with engine.begin() as conn:
        conn.execute(delete(db.transactions))
        conn.execute(delete(db.ticker_map))
        conn.execute(delete(db.price_cache))
        conn.execute(delete(db.price_history))
        conn.execute(delete(db.exchange_rates))
        conn.execute(delete(db.app_state))
