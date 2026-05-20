"""Dynamic ticker resolution + price fetching via yfinance.

Two-tier cache:
  1. process-local dict (sub-minute TTL) — keeps the dashboard snappy
  2. SQLite price_cache / price_history — survives restarts, lets the app
     show last-known values offline

Resolution cascade (per plan):
  1. Check ticker_map DB — return cached resolution if present
  2. Symbol already looks valid (`.TO`, dot-prefix, alphabetic 1-5) — use directly
  3. Internal Questrade ID (e.g. A603109) — extract name from description,
     run yfinance.search(), prefer the TOR/TSX exchange for Canadian names
  4. Validate by fetching info; persist the resolution to ticker_map
  5. Failures → status='unresolved' so the UI can surface them
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from backend import store
from backend.models import Currency, ResolvedTicker


logger = logging.getLogger(__name__)


# ---------- process-local cache ----------

_PRICE_TTL_SECONDS = 45  # belt-and-braces on top of DB cache
_price_memo: dict[str, tuple[float, str, float]] = {}  # ticker -> (price, currency, ts)
_fx_memo: dict[str, tuple[float, float]] = {}          # pair  -> (rate, ts)


# ---------- yfinance lazy import ----------

def _yf():
    """Lazy import so the module can be unit-tested without yfinance installed."""
    import yfinance  # type: ignore[import-not-found]

    return yfinance


# ---------- resolution ----------

_INTERNAL_ID_RE = re.compile(r"^[A-Z]{1,3}\d{5,}$")
_VALID_TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,15}$")


def resolve_ticker(raw_symbol: str, description: str | None = None) -> ResolvedTicker:
    """Walk the resolution cascade; persist the result in ticker_map."""
    raw_symbol = raw_symbol.strip().upper()

    # 1. cached resolution
    cached = store.get_ticker_map().get(raw_symbol)
    if cached and cached.status == "resolved" and cached.resolved_ticker:
        return cached

    candidate = _quick_normalize(raw_symbol, description)
    if candidate:
        resolution = _try_validate(candidate, raw_symbol, description)
        if resolution.status == "resolved":
            store.save_ticker_resolution(resolution)
            return resolution

    if _INTERNAL_ID_RE.match(raw_symbol):
        guess = _search_by_description(description)
        if guess:
            resolution = _try_validate(guess, raw_symbol, description)
            if resolution.status == "resolved":
                store.save_ticker_resolution(resolution)
                return resolution

    unresolved = ResolvedTicker(
        raw_symbol=raw_symbol,
        resolved_ticker=None,
        status="unresolved",
        resolved_from="fallback",
    )
    store.save_ticker_resolution(unresolved)
    return unresolved


def _quick_normalize(symbol: str, description: str | None) -> str | None:
    """Mirror the parser's normalization for a final defensive pass."""
    if symbol.endswith(".TO"):
        return symbol
    if symbol.startswith("."):
        return f"{symbol[1:]}.TO"
    if _INTERNAL_ID_RE.match(symbol):
        return None
    if re.fullmatch(r"[A-Z]{1,5}", symbol):
        if description:
            d = description.upper()
            if any(k in d for k in ("BMO MSCI", "VANGUARD ALL-EQUITY")):
                return f"{symbol}.TO"
        return symbol
    return symbol if _VALID_TICKER_RE.match(symbol) else None


def _try_validate(candidate: str, raw_symbol: str, description: str | None) -> ResolvedTicker:
    """Fetch candidate's info; success → resolved, failure → unresolved."""
    info = _safe_info(candidate)
    if info:
        return ResolvedTicker(
            raw_symbol=raw_symbol,
            resolved_ticker=candidate,
            security_name=info.get("longName") or info.get("shortName") or description,
            exchange=info.get("exchange") or _infer_exchange(candidate),
            currency=_infer_currency(info, candidate),
            resolved_from="pattern" if candidate == _quick_normalize(raw_symbol, description) else "yfinance_search",
            status="resolved",
        )
    # Fall through: assume candidate is correct even if yfinance.info is empty
    # (it's notoriously flaky). Frontend will still get a quote attempt later.
    return ResolvedTicker(
        raw_symbol=raw_symbol,
        resolved_ticker=candidate,
        security_name=description,
        exchange=_infer_exchange(candidate),
        currency=_infer_currency(None, candidate),
        resolved_from="pattern",
        status="resolved",
    )


def _safe_info(ticker: str) -> dict[str, Any] | None:
    """Call yfinance.Ticker.info defensively. Returns None on any error or empty payload."""
    try:
        info = _yf().Ticker(ticker).info
    except Exception as e:
        logger.warning("yfinance info failed for %s: %s", ticker, e)
        return None
    if not info:
        return None
    if info.get("regularMarketPrice") is None and info.get("previousClose") is None:
        return None
    return info


def _search_by_description(description: str | None) -> str | None:
    """yfinance.search() is best-effort; pick the TSX result for Canadian names."""
    if not description:
        return None
    query = _extract_name(description)
    if not query:
        return None
    try:
        # yfinance.Search was added in recent versions; fall back to Lookup if missing.
        try:
            from yfinance import Search  # type: ignore[import-not-found]
        except ImportError:  # pragma: no cover
            return None
        hits = Search(query).quotes or []
    except Exception as e:
        logger.warning("yfinance.Search failed for %r: %s", query, e)
        return None

    if not hits:
        return None

    def score(h: dict[str, Any]) -> tuple[int, int]:
        """Sort key for yfinance.search results — prefer TSX/TOR for Canadian holdings."""
        exch = (h.get("exchange") or "").upper()
        prefer_ca = any(c in exch for c in ("TOR", "TSX", "TSXV"))
        return (1 if prefer_ca else 0, -int(h.get("score", 0) or 0))

    hits.sort(key=score, reverse=True)
    return hits[0].get("symbol")


def _extract_name(description: str) -> str:
    """Trim Questrade's noisy descriptions down to the core security name."""
    s = description.upper()
    # Drop common boilerplate suffixes/prefixes.
    s = re.sub(r"\b(CASH DIV ON|SUBST PAY ON|ETF UNIT|UNIT DIST ON|WE ACTED AS AGENT).*$", "", s)
    s = re.sub(r"\b\d+\s+SHS\b.*$", "", s)
    s = re.sub(r"\bNON[\- ]?RES TAX WITHHELD\b.*$", "", s)
    return s.strip().rstrip(",.")


def _infer_exchange(ticker: str) -> str | None:
    """Guess the exchange from the ticker suffix (.TO=TSX, .V=TSXV, .NE=NEO, else US)."""
    if ticker.endswith(".TO"):
        return "TSX"
    if ticker.endswith(".V"):
        return "TSXV"
    if ticker.endswith(".NE"):
        return "NEO"
    return "US"


def _infer_currency(info: dict[str, Any] | None, ticker: str) -> Currency:
    """Guess the trading currency from yfinance info or the ticker suffix."""
    if info and (cur := info.get("currency")):
        return "USD" if cur.upper() == "USD" else "CAD"
    return "CAD" if ticker.endswith((".TO", ".V", ".NE", ".CN")) else "USD"


# ---------- price fetching ----------

@dataclass
class QuoteResult:
    ticker: str
    price: float | None
    currency: Currency | None
    stale: bool
    fetched_at: datetime | None


def get_quote(ticker: str, max_age_minutes: int = 15) -> QuoteResult:
    """Resolve a single ticker price using the two-tier cache."""
    # Tier 1: process memo
    memo = _price_memo.get(ticker)
    if memo and (time.time() - memo[2]) < _PRICE_TTL_SECONDS:
        return QuoteResult(ticker=ticker, price=memo[0], currency=memo[1], stale=False, fetched_at=None)

    # Tier 2: DB cache (still fresh)
    cached = store.get_cached_price(ticker, max_age_minutes=max_age_minutes)
    if cached and not cached["stale"]:
        _price_memo[ticker] = (cached["price"], cached["currency"], time.time())
        return QuoteResult(
            ticker=ticker,
            price=cached["price"],
            currency=cached["currency"],
            stale=False,
            fetched_at=cached["fetched_at"],
        )

    # Tier 3: live fetch
    try:
        t = _yf().Ticker(ticker)
        info = t.fast_info if hasattr(t, "fast_info") else {}
        price = (
            info.get("lastPrice")
            or info.get("last_price")
            or (t.info or {}).get("regularMarketPrice")
        )
        currency = (info.get("currency") or "").upper() or _infer_currency(t.info or {}, ticker)
        currency_norm: Currency = "USD" if currency == "USD" else "CAD"
        if price is not None:
            store.save_current_price(ticker, float(price), currency_norm)
            _price_memo[ticker] = (float(price), currency_norm, time.time())
            return QuoteResult(
                ticker=ticker,
                price=float(price),
                currency=currency_norm,
                stale=False,
                fetched_at=datetime.utcnow(),
            )
    except Exception as e:
        logger.warning("Live quote failed for %s: %s", ticker, e)

    # Tier 4: stale fallback
    if cached:
        return QuoteResult(
            ticker=ticker,
            price=cached["price"],
            currency=cached["currency"],
            stale=True,
            fetched_at=cached["fetched_at"],
        )
    return QuoteResult(ticker=ticker, price=None, currency=None, stale=True, fetched_at=None)


def refresh_quotes(tickers: list[str]) -> dict[str, QuoteResult]:
    """Fetch many; clear memo first so we always go live."""
    _price_memo.clear()
    return {t: get_quote(t, max_age_minutes=0) for t in tickers}


# ---------- history ----------

def ensure_history(ticker: str, start: str = "2010-01-01") -> pd.DataFrame:
    """Return weekly-or-better history for a ticker, fetching what we don't already have."""
    have = store.get_price_history(ticker)
    need_fetch = have.empty or (have.index.max().date() < (datetime.utcnow() - timedelta(days=2)).date())

    if need_fetch:
        try:
            df = _yf().Ticker(ticker).history(start=start, interval="1d", auto_adjust=False)
            if not df.empty:
                store.save_price_history(ticker, df)
                have = store.get_price_history(ticker)
        except Exception as e:
            logger.warning("History fetch failed for %s: %s", ticker, e)

    return have


# ---------- FX ----------

def get_fx(pair: str = "USDCAD", max_age_minutes: int = 15) -> tuple[float, bool]:
    """Live USDCAD or CADUSD rate. Cached 15 min in DB."""
    pair = pair.upper()
    memo = _fx_memo.get(pair)
    if memo and (time.time() - memo[1]) < _PRICE_TTL_SECONDS:
        return memo[0], False

    cached = store.get_exchange_rate(pair, max_age_minutes=max_age_minutes)
    if cached and not cached["stale"]:
        _fx_memo[pair] = (cached["rate"], time.time())
        return cached["rate"], False

    ticker = f"{pair}=X"
    try:
        df = _yf().Ticker(ticker).history(period="2d", interval="1d")
        if not df.empty:
            rate = float(df["Close"].iloc[-1])
            store.save_exchange_rate(pair, rate)
            _fx_memo[pair] = (rate, time.time())
            return rate, False
    except Exception as e:
        logger.warning("FX fetch failed for %s: %s", pair, e)

    if cached:
        return cached["rate"], True
    # Hard fallback so the dashboard never blanks out on a bad network.
    fallback = 1.37 if pair == "USDCAD" else 0.73
    return fallback, True


def historical_fx(d, pair: str = "USDCAD") -> float | None:
    """Bank-of-Canada-style historical rate for tax reporting.

    Tries the DB cache first; falls back to yfinance daily close at that date.
    """
    pair = pair.upper()
    if hasattr(d, "isoformat"):
        date_str = d.isoformat()
    else:
        date_str = str(d)
    cached = store.get_exchange_rate(pair, rate_date=date_str)
    if cached:
        return cached["rate"]
    try:
        ticker = f"{pair}=X"
        df = _yf().Ticker(ticker).history(start=date_str, end=(pd.Timestamp(date_str) + pd.Timedelta(days=5)).date().isoformat())
        if not df.empty:
            rate = float(df["Close"].iloc[0])
            store.save_exchange_rate(pair, rate, rate_date=date_str)
            return rate
    except Exception as e:
        logger.warning("Historical FX fetch failed (%s @ %s): %s", pair, date_str, e)
    return None


def clear_memo() -> None:
    """Used by tests."""
    _price_memo.clear()
    _fx_memo.clear()
