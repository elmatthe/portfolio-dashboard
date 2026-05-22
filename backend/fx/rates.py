"""FX rate service — historical local-currency → CAD conversion.

Priority (per CLAUDE_CODE_INSTRUCTIONS §3.2):
    1. In-file rate cache (set by the parser when the broker file embedded it)
    2. Bank of Canada historical Valet API — only when FX_LIVE_RATES=true
    3. Static fallback table (offline / tests)

CRITICAL: rates are always looked up at the TRANSACTION DATE, never today's
rate. This is the CRA-correct approach for capital gains across non-CAD
trades (the same enforcement that tsiemens/acb and dwrpayne/portfolio
implement). Daily caching is keyed on (pair, rate_date) in the existing
exchange_rates SQLite table, so subsequent imports of the same trade date
reuse the cached rate.

Bank of Canada Valet API:
    https://www.bankofcanada.ca/valet/observations/<series>/json
        ?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD
    Series IDs: FXUSDCAD, FXGBPCAD, FXEURCAD, FXJPYCAD, FXAUDCAD, FXCHFCAD
    Daily observations back to 2017. Weekends/holidays return no rows;
    we then walk backwards up to 7 days to find the most recent rate.
    BoC does not publish CAD/HKD, CAD/SEK, CAD/NOK — those fall through to
    the static table.
"""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from threading import Lock
from typing import ClassVar

logger = logging.getLogger(__name__)


# ---------- Static fallback ----------

STATIC_RATES_TO_CAD: dict[str, float] = {
    "CAD": 1.00,
    "USD": 1.36,
    "GBP": 1.72,
    "EUR": 1.48,
    "JPY": 0.0091,
    "AUD": 0.89,
    "CHF": 1.50,
    "HKD": 0.174,
    "SEK": 0.126,
    "NOK": 0.126,
}


# Currencies for which the Bank of Canada publishes a CAD-denominated Valet
# series. HKD/SEK/NOK are NOT published by BoC — they fall through to the
# static table regardless of FX_LIVE_RATES, so trades in those currencies will
# always be converted at the 2024 spot rates baked into STATIC_RATES_TO_CAD.
# If sub-1% FX accuracy matters for HKD/SEK/NOK exposure, add another data
# source here (e.g. exchangerate.host) rather than expecting BoC coverage.
BOC_SERIES_IDS: dict[str, str] = {
    "USD": "FXUSDCAD",
    "GBP": "FXGBPCAD",
    "EUR": "FXEURCAD",
    "JPY": "FXJPYCAD",
    "AUD": "FXAUDCAD",
    "CHF": "FXCHFCAD",
}


# ---------- Service ----------

class FXService:
    """Multi-source FX rate provider.

    Usage:
        svc = get_fx_service()
        rate = svc.rate_to_cad("GBP", date(2024, 6, 1))     # → 1.72-ish
        cad  = svc.convert_to_cad(100.00, "GBP", date(2024, 6, 1))
    """

    STATIC_RATES: ClassVar[dict[str, float]] = STATIC_RATES_TO_CAD

    def __init__(self, *, live_enabled: bool | None = None) -> None:
        """`live_enabled=None` (default) reads the FX_LIVE_RATES env var."""
        if live_enabled is None:
            live_enabled = os.environ.get("FX_LIVE_RATES", "").lower() in {"1", "true", "yes", "on"}
        self.live_enabled = live_enabled
        # In-file overrides: parser sets `service.register_in_file_rate(...)` when
        # the broker export already contained a rate for that (currency, date).
        self._in_file: dict[tuple[str, str], float] = {}
        # In-memory cache for the current process — sits in front of the
        # SQLite exchange_rates table to avoid round-trips in tight loops.
        self._memo: dict[tuple[str, str], float] = {}
        self._lock = Lock()

    # ---- public API ----

    def register_in_file_rate(self, currency: str, trade_date: date, rate: float) -> None:
        """Parser hook: stash a rate the broker file gave us so the lookup
        priority can prefer it over BoC/static for that exact day."""
        key = (currency.upper(), trade_date.isoformat())
        self._in_file[key] = float(rate)

    def rate_to_cad(self, currency: str, trade_date: date) -> float:
        """Return the rate at which 1 unit of `currency` converts to CAD on
        `trade_date`. CAD → 1.0 exactly."""
        currency = (currency or "CAD").upper()
        if currency == "CAD":
            return 1.0
        key = (currency, trade_date.isoformat())

        # 1. In-file override
        if key in self._in_file:
            return self._in_file[key]

        # 2. Process memo
        if key in self._memo:
            return self._memo[key]

        # 3. SQLite cache
        cached = _get_cached_rate(currency, trade_date)
        if cached is not None:
            self._memo[key] = cached
            return cached

        # 4. Live BoC lookup (only if enabled and series exists)
        if self.live_enabled and currency in BOC_SERIES_IDS:
            live = self._fetch_boc(currency, trade_date)
            if live is not None:
                _save_cached_rate(currency, trade_date, live)
                self._memo[key] = live
                return live

        # 5. Static fallback
        rate = self.STATIC_RATES.get(currency)
        if rate is None:
            logger.warning("No FX rate available for %s — defaulting to 1.0", currency)
            rate = 1.0
        self._memo[key] = rate
        return rate

    def convert_to_cad(self, amount: float, currency: str, trade_date: date) -> float:
        """Convert `amount` (in `currency`) to CAD on `trade_date`. Rounded to 2dp."""
        rate = self.rate_to_cad(currency, trade_date)
        return round(amount * rate, 2)

    def populate_transaction(self, tx) -> None:
        """Fill `tx.fx_rate_to_cad` and `tx.net_cad` if they're not already set."""
        if tx.fx_rate_to_cad is None:
            tx.fx_rate_to_cad = self.rate_to_cad(tx.currency, tx.transaction_date)
        if tx.net_cad is None and tx.net_amount is not None:
            tx.net_cad = round(tx.net_amount * tx.fx_rate_to_cad, 2)

    # ---- BoC live fetch ----

    def _fetch_boc(self, currency: str, trade_date: date) -> float | None:
        """Hit the Bank of Canada Valet API for one observation.

        Returns None on any failure (network, parse, weekend/holiday with no
        prior observation in the 7-day lookback window) — caller falls back
        to static.
        """
        series = BOC_SERIES_IDS.get(currency)
        if not series:
            return None
        # BoC weekends + holidays: query a 7-day window ending on the trade
        # date so we always get at least one row when markets were closed.
        start = trade_date - timedelta(days=7)
        end = trade_date
        url = (
            f"https://www.bankofcanada.ca/valet/observations/{series}/json"
            f"?start_date={start.isoformat()}&end_date={end.isoformat()}"
        )
        try:
            import urllib.request
            with urllib.request.urlopen(url, timeout=10) as resp:
                import json
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.warning("BoC fetch failed for %s on %s: %s", currency, trade_date, e)
            return None
        observations = payload.get("observations") or []
        # Walk newest-first to find the most recent rate on or before trade_date
        for obs in reversed(observations):
            try:
                obs_date_str = obs.get("d")
                val = obs.get(series, {}).get("v")
                if obs_date_str and val:
                    return float(val)
            except (KeyError, ValueError, TypeError):
                continue
        return None


# ---------- Storage helpers (delegate to store.py) ----------

def _get_cached_rate(currency: str, trade_date: date) -> float | None:
    """Look up a previously-fetched rate keyed on (pair, rate_date)."""
    try:
        from backend import store  # late import to avoid cycle with db.py
        pair = f"{currency}CAD"
        row = store.get_exchange_rate(pair, rate_date=trade_date.isoformat())
        if row is not None:
            return float(row["rate"])
    except Exception as e:
        logger.debug("FX cache lookup failed: %s", e)
    return None


def _save_cached_rate(currency: str, trade_date: date, rate: float) -> None:
    """Persist a newly-fetched live rate so the next import doesn't refetch."""
    try:
        from backend import store
        pair = f"{currency}CAD"
        store.save_exchange_rate(pair=pair, rate=rate, rate_date=trade_date.isoformat())
    except Exception as e:
        logger.debug("FX cache save failed: %s", e)


# ---------- Singleton accessor ----------

_singleton: FXService | None = None
_singleton_lock = Lock()


def get_fx_service() -> FXService:
    """Process-wide FXService singleton."""
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = FXService()
    return _singleton
