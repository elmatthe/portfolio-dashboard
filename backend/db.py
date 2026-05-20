"""SQLite schema + engine factory.

The DB path comes from PORTFOLIO_DB_PATH (set by the Electron main process
to the OS-standard userData directory). In dev, falls back to ./data/portfolio.db
relative to the project root.
"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.engine import Engine


metadata = MetaData()


transactions = Table(
    "transactions",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("hash", String, nullable=False, unique=True, index=True),
    Column("broker", String, nullable=False),
    Column("transaction_date", String, nullable=False, index=True),
    Column("settlement_date", String, nullable=True),
    Column("action", String, nullable=False, index=True),
    Column("raw_symbol", String, nullable=True),
    Column("resolved_ticker", String, nullable=True, index=True),
    Column("description", String, nullable=False, default=""),
    Column("quantity", Float, nullable=False, default=0.0),
    Column("price", Float, nullable=False, default=0.0),
    Column("gross_amount", Float, nullable=False, default=0.0),
    Column("commission", Float, nullable=False, default=0.0),
    Column("net_amount", Float, nullable=False, default=0.0),
    Column("currency", String, nullable=False, default="CAD"),
    Column("account_number", String, nullable=False),
    Column("account_type", String, nullable=False, index=True),
    Column("imported_at", DateTime, nullable=False),
    # ---- v0.3.0 multi-currency fields (all nullable for backwards compatibility) ----
    Column("fx_rate_to_cad", Float, nullable=True),
    Column("net_cad", Float, nullable=True),
    Column("isin", String, nullable=True),
    Column("exchange", String, nullable=True),
    Column("reference_id", String, nullable=True),
)


ticker_map = Table(
    "ticker_map",
    metadata,
    Column("raw_symbol", String, primary_key=True),
    Column("resolved_ticker", String, nullable=True),
    Column("security_name", String, nullable=True),
    Column("exchange", String, nullable=True),
    Column("currency", String, nullable=True),
    Column("resolved_from", String, nullable=True),  # "pattern", "yfinance_search", "manual"
    Column("status", String, nullable=False, default="resolved"),  # "resolved" | "unresolved"
    Column("resolved_at", DateTime, nullable=False),
)


price_cache = Table(
    "price_cache",
    metadata,
    Column("ticker", String, primary_key=True),
    Column("price", Float, nullable=False),
    Column("currency", String, nullable=False),
    Column("fetched_at", DateTime, nullable=False),
)


price_history = Table(
    "price_history",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ticker", String, nullable=False, index=True),
    Column("date", String, nullable=False),
    Column("open", Float, nullable=True),
    Column("high", Float, nullable=True),
    Column("low", Float, nullable=True),
    Column("close", Float, nullable=False),
    Column("volume", Float, nullable=True),
    UniqueConstraint("ticker", "date", name="uq_price_history_ticker_date"),
)


exchange_rates = Table(
    "exchange_rates",
    metadata,
    Column("pair", String, nullable=False),
    Column("rate", Float, nullable=False),
    Column("rate_date", String, nullable=True),  # YYYY-MM-DD for historical rates; null = live
    Column("fetched_at", DateTime, nullable=False),
    UniqueConstraint("pair", "rate_date", name="uq_exchange_rates_pair_date"),
)


app_state = Table(
    "app_state",
    metadata,
    Column("key", String, primary_key=True),
    Column("value", String, nullable=True),
)


price_alerts = Table(
    "price_alerts",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ticker", String, nullable=False, index=True),
    Column("alert_type", String, nullable=False),      # "above" | "below"
    Column("target_price", Float, nullable=False),
    Column("currency", String, nullable=False, default="CAD"),
    Column("triggered", Integer, nullable=False, default=0),    # 0 / 1
    Column("triggered_at", DateTime, nullable=True),
    Column("dismissed", Integer, nullable=False, default=0),     # 0 / 1
    Column("created_at", DateTime, nullable=False),
)


_db_path_override: Path | None = None


def set_db_path(path: Path | str) -> None:
    """Hot-swap the DB file used by subsequent get_engine() calls.

    Used by the profile-switch endpoint: disposes the existing engine so the
    next get_engine() rebinds to the new profile's portfolio.db.
    """
    global _db_path_override
    _db_path_override = Path(path)
    _db_path_override.parent.mkdir(parents=True, exist_ok=True)
    reset_engine_for_tests()  # disposes any cached engine


def resolve_db_path() -> Path:
    """Return the SQLite file path. Precedence:

    1. The explicit override set by set_db_path() (used by profile switching).
    2. The active profile's portfolio.db, if PORTFOLIO_PROFILES_DIR is configured.
    3. PORTFOLIO_DB_PATH env var (legacy single-DB mode).
    4. ./data/portfolio.db relative to the project root (dev fallback).
    """
    if _db_path_override is not None:
        p = _db_path_override
    else:
        env_path = os.environ.get("PORTFOLIO_DB_PATH")
        if env_path:
            p = Path(env_path)
        else:
            # Profile-aware fallback: if PORTFOLIO_PROFILES_DIR is set, route to
            # the active profile's DB. Import lazily to avoid circular import.
            try:
                from backend import profiles as _profiles

                if os.environ.get("PORTFOLIO_PROFILES_DIR"):
                    active = _profiles.get_active_profile()
                    p = _profiles.profile_db_path(active.id)
                else:
                    project_root = Path(__file__).resolve().parent.parent
                    p = project_root / "data" / "portfolio.db"
            except Exception:
                project_root = Path(__file__).resolve().parent.parent
                p = project_root / "data" / "portfolio.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@event.listens_for(Engine, "connect")
def _configure_sqlite(dbapi_connection, connection_record):
    """Configure every fresh SQLite connection.

    busy_timeout is the critical one: without it, concurrent writers
    (e.g. several parallel /api/history/<ticker> calls all upserting OHLCV rows)
    return SQLITE_BUSY immediately and SQLAlchemy raises OperationalError.
    With WAL mode + a 5 s busy_timeout, write attempts wait for the lock to
    release instead of failing.
    """
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()
    except Exception:
        pass


_engine: Engine | None = None


def get_engine() -> Engine:
    """Lazy-initialise a process-wide SQLAlchemy engine bound to the resolved DB path."""
    global _engine
    if _engine is None:
        db_path = resolve_db_path()
        url = f"sqlite:///{db_path.as_posix()}"
        _engine = create_engine(
            url,
            future=True,
            # SQLite + threadpool: FastAPI runs handlers on a threadpool by
            # default, so connections must be shareable across threads.
            connect_args={"check_same_thread": False, "timeout": 5.0},
            # Pool size of 1 forces every request through a single connection
            # — which combined with WAL + busy_timeout means writes serialize
            # naturally rather than collide on a per-connection cursor.
            pool_pre_ping=True,
        )
        metadata.create_all(_engine)
        _migrate_schema(_engine)
    return _engine


def _migrate_schema(engine: Engine) -> None:
    """Idempotent schema migrations for DBs that pre-date v0.3.0.

    SQLAlchemy's create_all only creates missing tables; it won't add columns
    to a table that already exists. We use PRAGMA table_info to inspect each
    table and ALTER TABLE … ADD COLUMN any v0.3.0 columns that are missing.
    """
    additions = {
        "transactions": [
            ("fx_rate_to_cad", "REAL"),
            ("net_cad", "REAL"),
            ("isin", "TEXT"),
            ("exchange", "TEXT"),
            ("reference_id", "TEXT"),
        ],
    }
    with engine.begin() as conn:
        for table_name, cols in additions.items():
            existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table_name})")}
            for col_name, col_type in cols:
                if col_name not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}")


def reset_engine_for_tests() -> None:
    """Dispose the global engine — used by tests to swap PORTFOLIO_DB_PATH."""
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None


def db_size_kb() -> int:
    """Size of the active SQLite database file in KB (0 if not yet created)."""
    path = resolve_db_path()
    if not path.exists():
        return 0
    return path.stat().st_size // 1024
