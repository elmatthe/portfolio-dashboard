"""Aggregation pipeline. Pure read from DB; produces the PortfolioData payload."""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Iterable

import numpy as np
import pandas as pd

from backend import market_data, store
from backend._time import utcnow_naive as _now
from backend.acb import compute as compute_acb
from backend.models import (
    AccountBalances,
    AccountTab,
    AccountType,
    AttributionReport,
    AttributionRow,
    BenchmarkPoint,
    CorrelationMatrix,
    DividendReport,
    DividendYieldRow,
    ExchangeRateInfo,
    Holding,
    HistoricalDataPoint,
    MonthlyDividend,
    PortfolioData,
    PortfolioStats,
    PortfolioValuePoint,
    Transaction,
    UnresolvedTicker,
    UpcomingDividend,
)


DEFAULT_RISK_FREE = 0.0375


# ---------- time period helpers ----------

VALID_PERIODS = ("1m", "3m", "6m", "ytd", "1y", "3y", "all")


def period_to_start_date(period: str | None) -> date:
    """Map a period label to a calendar start date.

    "all" returns a sentinel far-past date so callers can treat it uniformly.
    Unknown values fall back to "all" rather than raising — the period filter
    is a UX nicety, not a correctness boundary.
    """
    today = date.today()
    if not period:
        return date(2000, 1, 1)
    p = period.lower()
    if p == "1m":
        return today - timedelta(days=30)
    if p == "3m":
        return today - timedelta(days=90)
    if p == "6m":
        return today - timedelta(days=180)
    if p == "ytd":
        return date(today.year, 1, 1)
    if p == "1y":
        return today - timedelta(days=365)
    if p == "3y":
        return today - timedelta(days=1095)
    return date(2000, 1, 1)


def normalize_period(period: str | None) -> str:
    """Return the canonical period label.

    None / empty string defaults to 'all'. Any other value MUST be one of
    VALID_PERIODS — unknown values raise HTTP 422 rather than silently falling
    through to 'all' (#PORT-3 in the audit).
    """
    if not period:
        return "all"
    p = period.lower()
    if p in VALID_PERIODS:
        return p
    from fastapi import HTTPException
    raise HTTPException(
        status_code=422,
        detail=f"Invalid period '{period}'. Valid values: {sorted(VALID_PERIODS)}",
    )


_ACCOUNT_LABELS: dict[str, str] = {
    "TFSA": "TFSA",
    "Margin": "Margin",
    "RRSP": "RRSP",
    "RESP": "RESP",
    "Crypto": "Crypto",
}


def list_account_tabs() -> list[AccountTab]:
    """Build the tab list straight from the transactions table — one tab per
    (account_type, account_number) pair, plus an "All Accounts" entry.
    """
    txs = store.get_all_transactions()
    seen: dict[str, tuple[str, str]] = {}  # account_number -> (account_type, account_number)
    for t in txs:
        if t.account_number and t.account_number not in seen:
            seen[t.account_number] = (t.account_type, t.account_number)

    tabs: list[AccountTab] = [AccountTab(key="all", label="All Accounts")]
    for account_type, account_number in sorted(
        seen.values(), key=lambda x: (_account_sort_key(x[0]), x[1])
    ):
        tabs.append(
            AccountTab(
                key=account_number,
                label=f"{_ACCOUNT_LABELS.get(account_type, account_type)} · {account_number}",
                account_type=account_type,  # type: ignore[arg-type]
                account_number=account_number,
            )
        )
    return tabs


def _account_sort_key(account_type: str) -> int:
    """Sort order for account-type chips so Margin shows before TFSA, etc."""
    return {"Margin": 0, "TFSA": 1, "RRSP": 2, "RESP": 3, "Crypto": 4}.get(account_type, 9)


def _resolve_active_tab(account: str | None, tabs: list[AccountTab]) -> AccountTab:
    """Map the query-param value to a concrete tab. `account` can be:
      - None / "" / "all"  → All Accounts
      - "margin" / "tfsa"  → first tab matching that account_type
      - "<number>"         → specific account_number

    Unknown values raise an HTTP 422 with the valid set surfaced in the detail
    — previously these silently fell through to "all", masquerading as a valid
    filter (#PORT-4 in the audit).
    """
    if not account or account.lower() == "all":
        return tabs[0]
    a = account.lower()
    for tab in tabs[1:]:
        if tab.account_number == account:
            return tab
        if tab.account_type and tab.account_type.lower() == a:
            return tab
    from fastapi import HTTPException
    valid = sorted({t.account_type for t in tabs[1:] if t.account_type} |
                   {t.account_number for t in tabs[1:] if t.account_number} |
                   {"all"})
    raise HTTPException(
        status_code=422,
        detail=f"Unknown account '{account}'. Valid values: {valid}",
    )


def build_portfolio(
    account: str | None = None,
    period: str | None = None,
    *,
    refresh_prices: bool = False,
) -> PortfolioData:
    """One-call aggregation. Used by GET /api/portfolio.

    `account` filters the response to a single account.
    `period` (1m / 3m / 6m / ytd / 1y / 3y / all) adds period-scoped fields to
    the response — period_return_pct on each holding, period_start_value_cad
    and period_return_cad/pct on each account, period_dividends_*, and a
    period-aware PortfolioStats.
    """
    txs = store.get_all_transactions()
    settings = store.get_settings()

    period_key = normalize_period(period)
    period_start = period_to_start_date(period_key)

    tabs = list_account_tabs()
    active = _resolve_active_tab(account, tabs)
    if active.account_number:
        txs = [t for t in txs if t.account_number == active.account_number]

    # For "all", set period_start to a sentinel BEFORE the first transaction so
    # `_value_history_at` returns the zero-value point that precedes the first
    # deposit. With period_start_value_cad=0 the denominator falls through to
    # net_deposits (correct lifetime ROI base). This is the primary fix for the
    # "period=all always returns 0%" bug — the block below now runs for every
    # period including "all".
    if period_key == "all":
        if txs:
            first_tx = min(t.transaction_date for t in txs)
            period_start = first_tx - timedelta(days=14)
        else:
            period_start = date.today()
    period_active = True

    # ACB & realized gains
    holdings_acb, gains_report = compute_acb(txs, security_names=_security_names(txs))

    # Live prices (or cached)
    tickers = sorted({h.ticker for h in holdings_acb.values()})
    quotes = {t: market_data.get_quote(t) for t in tickers}
    if refresh_prices:
        quotes.update(market_data.refresh_quotes(tickers))

    usd_cad, fx_stale = market_data.get_fx("USDCAD")
    fx_info = ExchangeRateInfo(
        usd_cad=usd_cad,
        cad_usd=1.0 / usd_cad if usd_cad else 0.0,
        fetched_at=_now(),
        stale=fx_stale,
    )

    # Build display holdings.
    # The grouping key MUST be (resolved_ticker, account_type) — never just ticker.
    # Same ticker held in both TFSA and Margin produces two separate holdings/cards.
    holdings: list[Holding] = []
    seen_keys: set[tuple[str, str]] = set()
    for (ticker, account), acb in holdings_acb.items():
        if acb.total_shares <= 0:
            continue
        assert (ticker, account) not in seen_keys, (
            f"duplicate holding key {(ticker, account)} — grouping must be per (ticker, account_type)"
        )
        seen_keys.add((ticker, account))
        q = quotes.get(ticker)
        price = q.price if q else None
        currency = acb.currency
        market_value = price * acb.total_shares if price is not None else None
        market_value_cad = _to_cad(market_value, currency, usd_cad) if market_value is not None else None
        unrealized = (market_value - acb.total_cost) if market_value is not None else None
        roi_pct = (unrealized / acb.total_cost * 100) if (unrealized is not None and acb.total_cost > 0) else None

        # Volatility / avg weekly return from cached history (no network in the hot path).
        hist_df = store.get_price_history(ticker)
        avg_w, ann_vol = _weekly_stats(hist_df)

        # Period-scoped metrics (only meaningful when ?period= is set)
        period_start_price = None
        period_return_pct = None
        period_dividends = 0.0
        if period_active:
            period_start_price = _price_at_or_before(hist_df, period_start)
            if period_start_price and price is not None and period_start_price > 0:
                period_return_pct = (price - period_start_price) / period_start_price * 100
            # Sum dividend net_amount for this (ticker, account) within the period.
            for t in txs:
                if (
                    t.action == "DIVIDEND"
                    and t.resolved_ticker == ticker
                    and t.account_type == account
                    and t.transaction_date >= period_start
                ):
                    period_dividends += t.net_amount

        holdings.append(
            Holding(
                ticker=ticker,
                security_name=acb.security_name,
                account_type=account,
                currency=currency,
                exchange=_infer_exchange(ticker),
                total_shares=acb.total_shares,
                acb_per_share=acb.acb_per_share,
                total_cost=acb.total_cost,
                total_commission=acb.total_commission,
                dividends_received=acb.dividends_received,
                current_price=price,
                price_fetched_at=q.fetched_at if q else None,
                price_is_stale=bool(q and q.stale),
                ticker_unresolved=False,
                market_value=market_value,
                market_value_cad=market_value_cad,
                unrealized_gain=unrealized,
                roi_pct=roi_pct,
                avg_weekly_return=avg_w,
                annualized_volatility=ann_vol,
                period_return_pct=period_return_pct,
                period_dividends_received=round(period_dividends, 2),
                period_start_price=period_start_price,
            )
        )

    # Account balances
    accounts = _aggregate_accounts(txs, holdings, usd_cad, period_start if period_active else None)
    combined = _combine_accounts(accounts, usd_cad)

    # Investment weights — share of holding's CAD market value over total equity
    total_equity_cad = combined.total_equity_cad or 0.0
    for h in holdings:
        if total_equity_cad > 0 and h.market_value_cad is not None:
            h.investment_weight_pct = h.market_value_cad / total_equity_cad * 100

    # Period-scoped metrics on the account/combined rows.
    # We reuse the value-history reconstruction (which is correctly per-
    # account_number) to figure out both the period-start AND period-end portfolio
    # value. This avoids the bug where `_aggregate_accounts` mis-attributes equity
    # when two accounts share an account_type (multiple Margin accounts at the same
    # broker, etc.) — there, `bal.total_equity_cad` is overwritten by whichever
    # account_type bucket the dict iteration lands on last. The value-history walk
    # filters txs by account_number per row, so it stays accurate per account.
    if period_active:
        all_history = portfolio_value_history(account=active.account_number or "all")
        period_start_total = _value_history_at(all_history, period_start) if period_key != "all" else 0.0
        period_end_total = all_history[-1].total_cad if all_history else 0.0
        for bal in [*accounts, combined]:
            bal.period_label = period_key
            # Per-account period start AND end value from the same per-account
            # value-history series — keeps both endpoints consistent and per-
            # account-number-accurate. For the combined row, reuse all_history.
            # For the lifetime "all" view, start value is forced to 0 so the
            # denominator falls through to total net deposits (the only
            # meaningful base for lifetime ROI).
            if bal is combined:
                bal.period_start_value_cad = period_start_total
                bal_cur = period_end_total
            else:
                slim = portfolio_value_history(account=bal.account_number)
                bal.period_start_value_cad = 0.0 if period_key == "all" else _value_history_at(slim, period_start)
                bal_cur = slim[-1].total_cad if slim else 0.0
            # Subtract net deposits made DURING the period so new contributions
            # don't get counted as portfolio return. TRANSFER actions are
            # internal cash flows that don't add to external capital — they must
            # be excluded from the denominator and from the cash-flow subtraction.
            net_dep_in_period = 0.0
            for t in txs:
                if t.action not in ("DEPOSIT", "CONTRIBUTION", "WITHDRAWAL"):
                    continue
                if t.transaction_date < period_start:
                    continue
                if bal is not combined and t.account_number != bal.account_number:
                    continue
                amt = t.net_amount * usd_cad if t.currency == "USD" else t.net_amount
                net_dep_in_period += amt
            bal.period_return_cad = round(
                bal_cur - bal.period_start_value_cad - net_dep_in_period, 2
            )
            # Denominator: period_start_value if available, else the deposits made
            # during the period (sensible for an account opened mid-period — and
            # for the all-time view where period_start_value is always 0).
            denom = bal.period_start_value_cad if bal.period_start_value_cad > 0 else net_dep_in_period
            bal.period_return_pct = (
                round(bal.period_return_cad / denom * 100, 2) if denom > 0 else 0.0
            )
            # Period dividends (sum from the filtered transaction set)
            for t in txs:
                if t.action != "DIVIDEND" or t.transaction_date < period_start:
                    continue
                if bal is not combined and t.account_number != bal.account_number:
                    continue
                if t.currency == "USD":
                    bal.period_dividends_usd += t.net_amount
                else:
                    bal.period_dividends_cad += t.net_amount

    # Portfolio-wide stats from a single weighted weekly return series, scoped
    # to the selected period when active.
    stats = _portfolio_stats(
        holdings,
        settings.risk_free_rate,
        period_start if period_active else None,
    )

    # Unresolved tickers surfaced from the ticker_map
    ticker_map = store.get_ticker_map()
    unresolved_counts: dict[str, int] = defaultdict(int)
    unresolved_descs: dict[str, str] = {}
    for t in txs:
        if not t.raw_symbol:
            continue
        cached = ticker_map.get(t.raw_symbol.upper())
        if cached and cached.status == "unresolved":
            unresolved_counts[t.raw_symbol] += 1
            unresolved_descs.setdefault(t.raw_symbol, t.description)
    unresolved = [
        UnresolvedTicker(raw_symbol=s, description=unresolved_descs.get(s), occurrences=c)
        for s, c in unresolved_counts.items()
    ]

    last_refresh = None
    last_refresh_str = store.get_state("last_price_refresh_at")
    if last_refresh_str:
        try:
            last_refresh = datetime.fromisoformat(last_refresh_str)
        except ValueError:
            pass

    return PortfolioData(
        accounts=accounts,
        combined=combined,
        holdings=sorted(holdings, key=lambda h: (h.account_type, -(h.market_value_cad or 0))),
        capital_gains=gains_report,
        stats=stats,
        exchange_rate=fx_info,
        last_import=store.get_last_import_info(),
        last_price_refresh_at=last_refresh,
        unresolved_tickers=unresolved,
        tabs=tabs,
        active_tab=active.key,
        period=period_key,
        period_start_date=period_start if period_active else None,
    )


# ---------- helpers ----------

def _security_names(txs: Iterable[Transaction]) -> dict[str, str]:
    """Build a ticker → display name map from descriptions. Best-effort."""
    names: dict[str, str] = {}
    for t in txs:
        if not t.resolved_ticker or t.resolved_ticker in names:
            continue
        desc = (t.description or "").strip()
        if desc:
            names[t.resolved_ticker] = _clean_name(desc)
    return names


def _clean_name(desc: str) -> str:
    """Trim Questrade-style boilerplate from a transaction description to get a readable security name."""
    # Trim the same boilerplate market_data trims, but keep title-case-ish.
    import re

    s = re.sub(r"\bCASH DIV ON .*$", "", desc, flags=re.I)
    s = re.sub(r"\bSUBST PAY ON .*$", "", s, flags=re.I)
    s = re.sub(r"\b(ETF UNIT|UNIT DIST ON).*$", "", s, flags=re.I)
    s = re.sub(r"\bWE ACTED AS AGENT.*$", "", s, flags=re.I)
    s = s.strip(", ").strip()
    return s.title() if s.isupper() else s


def _infer_exchange(ticker: str) -> str | None:
    """Map ticker suffix to a displayable exchange label."""
    if ticker.endswith(".TO"):
        return "TSX"
    if ticker.endswith(".V"):
        return "TSXV"
    if ticker.endswith(".NE"):
        return "NEO"
    return "NYSE/NASDAQ"


def _price_at_or_before(df: pd.DataFrame, d: date) -> float | None:
    """Return the most recent daily close on or before `d`. None if no row exists."""
    if df is None or df.empty or "close" not in df.columns:
        return None
    ts = pd.Timestamp(d)
    applicable = df[df.index <= ts]
    if applicable.empty:
        return None
    val = applicable["close"].iloc[-1]
    if pd.isna(val):
        return None
    return float(val)


def _value_history_at(points: list, d: date) -> float:
    """Pick the first portfolio-value point on or after `d`. Falls back to the
    last available point if `d` is past all of them.
    """
    if not points:
        return 0.0
    for p in points:
        if p.date >= d:
            return p.total_cad
    return points[-1].total_cad


def _to_cad(amount: float | None, currency: str, usd_cad: float) -> float | None:
    """Convert a native-currency amount to CAD using the live FX rate."""
    if amount is None:
        return None
    if currency == "USD":
        return amount * usd_cad
    return amount


def _aggregate_accounts(
    txs: list[Transaction],
    holdings: list[Holding],
    usd_cad: float,
    period_start: date | None = None,
) -> list[AccountBalances]:
    """Per-account cash flow + equity totals, derived from raw transactions.

    Grouping key is account_number (not account_type), so a user with two Margin
    accounts gets two rows. Each row carries its account_type for display.

    `period_start` is accepted for forward-compat; current totals (Total Equity,
    Cash Remaining, etc.) are always point-in-time and not period-filtered per
    the plan. Period fields on the AccountBalances are populated by the caller
    in `build_portfolio` after this returns.
    """
    by_acct: dict[str, AccountBalances] = {}

    for t in txs:
        bal = by_acct.setdefault(
            t.account_number,
            AccountBalances(
                account_type=t.account_type,
                account_number=t.account_number,
                account_label=f"{_ACCOUNT_LABELS.get(t.account_type, t.account_type)} · {t.account_number}",
            ),
        )
        amt = t.net_amount
        if t.action in ("DEPOSIT", "CONTRIBUTION"):
            if t.currency == "USD":
                bal.cash_deposited_usd += amt
            else:
                bal.cash_deposited_cad += amt
        elif t.action == "WITHDRAWAL":
            if t.currency == "USD":
                bal.cash_deposited_usd += amt  # amt is negative
            else:
                bal.cash_deposited_cad += amt
        elif t.action == "BUY":
            if t.currency == "USD":
                bal.cash_invested_usd += abs(amt)
            else:
                bal.cash_invested_cad += abs(amt)
        elif t.action == "DIVIDEND":
            if t.currency == "USD":
                bal.total_dividends_usd += amt
            else:
                bal.total_dividends_cad += amt
        elif t.action == "FEE":
            if t.currency == "USD":
                bal.total_fees_usd += abs(amt)
            else:
                bal.total_fees_cad += abs(amt)

        # Commission is baked into BUY/SELL net_amount, but we still want to surface it
        if t.action in ("BUY", "SELL") and t.commission:
            if t.currency == "USD":
                bal.total_fees_usd += abs(t.commission)
            else:
                bal.total_fees_cad += abs(t.commission)

    # Equity from holdings — attribute each holding to the balance row whose
    # account_type matches. (Holdings carry account_type, not account_number;
    # if the user ever has multiple accounts of the same type this'd need
    # a richer Holding key.)
    by_type = {bal.account_type: bal for bal in by_acct.values()}
    for h in holdings:
        bal = by_type.get(h.account_type)
        if bal is None:
            continue
        if h.market_value is None:
            continue
        if h.currency == "USD":
            bal.total_equity_usd += h.market_value
        else:
            bal.total_equity_cad += h.market_value
        if h.unrealized_gain is not None:
            if h.currency == "USD":
                bal.unrealized_gain_usd += h.unrealized_gain
            else:
                bal.unrealized_gain_cad += h.unrealized_gain

    for bal in by_acct.values():
        bal.cash_remaining_cad = round(
            bal.cash_deposited_cad
            + bal.total_dividends_cad
            - bal.cash_invested_cad
            - bal.total_fees_cad,
            2,
        )
        bal.cash_remaining_usd = round(
            bal.cash_deposited_usd
            + bal.total_dividends_usd
            - bal.cash_invested_usd
            - bal.total_fees_usd,
            2,
        )

        # Bug 2 fix: Total Equity (as Questrade defines it) = Market Value + Cash balance.
        # Each currency's total equity now includes that currency's cash.
        bal.total_equity_cad = round(bal.total_equity_cad + bal.cash_remaining_cad, 2)
        bal.total_equity_usd = round(bal.total_equity_usd + bal.cash_remaining_usd, 2)

        # ROI matches Questrade's "Simple Rate of Return" — uses NET DEPOSITS
        # (money the user actually put into the account) as the denominator,
        # everything converted to CAD so USD/CAD mixing can't make positive and
        # negative values cancel out (Bug 3).
        total_equity_cad_eq = bal.total_equity_cad + bal.total_equity_usd * usd_cad
        deposited_cad_eq = bal.cash_deposited_cad + bal.cash_deposited_usd * usd_cad
        if deposited_cad_eq > 0:
            bal.overall_roi_pct = (total_equity_cad_eq - deposited_cad_eq) / deposited_cad_eq * 100

        invested_cad_eq = bal.cash_invested_cad + bal.cash_invested_usd * usd_cad
        if deposited_cad_eq > 0:
            bal.investment_weight_pct = invested_cad_eq / deposited_cad_eq * 100

    return sorted(by_acct.values(), key=lambda b: b.account_type)


def _combine_accounts(accounts: list[AccountBalances], usd_cad: float) -> AccountBalances:
    """Aggregate per-account balances into a single 'Combined' row, recomputing ROI in CAD-equivalent."""
    c = AccountBalances(account_type="Margin")  # placeholder; consumed only via "combined"
    for a in accounts:
        c.cash_deposited_cad += a.cash_deposited_cad
        c.cash_deposited_usd += a.cash_deposited_usd
        c.cash_invested_cad += a.cash_invested_cad
        c.cash_invested_usd += a.cash_invested_usd
        c.total_fees_cad += a.total_fees_cad
        c.total_fees_usd += a.total_fees_usd
        c.total_dividends_cad += a.total_dividends_cad
        c.total_dividends_usd += a.total_dividends_usd
        c.cash_remaining_cad += a.cash_remaining_cad
        c.cash_remaining_usd += a.cash_remaining_usd
        c.total_equity_cad += a.total_equity_cad
        c.total_equity_usd += a.total_equity_usd
        c.unrealized_gain_cad += a.unrealized_gain_cad
        c.unrealized_gain_usd += a.unrealized_gain_usd

    # Bug 3 fix: combined ROI must be computed AFTER summing all fields, and
    # must convert everything to a single currency so CAD/USD values don't cancel.
    total_equity_cad_eq = c.total_equity_cad + c.total_equity_usd * usd_cad
    deposited_cad_eq = c.cash_deposited_cad + c.cash_deposited_usd * usd_cad
    if deposited_cad_eq > 0:
        c.overall_roi_pct = (total_equity_cad_eq - deposited_cad_eq) / deposited_cad_eq * 100

    invested_cad_eq = c.cash_invested_cad + c.cash_invested_usd * usd_cad
    if deposited_cad_eq > 0:
        c.investment_weight_pct = invested_cad_eq / deposited_cad_eq * 100

    return c


# ---------- weekly returns / Sharpe / correlation ----------

def _weekly_close(df: pd.DataFrame) -> pd.Series:
    """Resample a daily close DataFrame to weekly bars."""
    if df is None or df.empty or "close" not in df.columns:
        return pd.Series(dtype=float)
    s = df["close"].copy()
    s.index = pd.to_datetime(s.index)
    return s.resample("W").last().dropna()


def _weekly_returns(df: pd.DataFrame) -> pd.Series:
    """Weekly percentage-change series derived from _weekly_close."""
    s = _weekly_close(df)
    if s.empty or len(s) < 2:
        return pd.Series(dtype=float)
    return s.pct_change().dropna()


def _weekly_stats(df: pd.DataFrame) -> tuple[float | None, float | None]:
    """Average weekly return + annualised volatility, or (None, None) if there's no usable history."""
    r = _weekly_returns(df)
    if r.empty:
        return None, None
    avg = float(r.mean())
    vol = float(r.std() * math.sqrt(52))
    return avg, vol


def _portfolio_stats(
    holdings: list[Holding],
    risk_free: float,
    period_start: date | None = None,
) -> PortfolioStats:
    """Equally-weighted weekly-return portfolio stats. Good enough for the dashboard.

    When `period_start` is provided, filter the weekly-return series to dates
    >= period_start before computing observations / total / annualised / Sharpe.
    """
    series_list: list[pd.Series] = []
    weights: list[float] = []
    total_value = sum((h.market_value_cad or 0) for h in holdings) or 1.0
    for h in holdings:
        df = store.get_price_history(h.ticker)
        r = _weekly_returns(df)
        if period_start is not None:
            r = r[r.index >= pd.Timestamp(period_start)]
        if r.empty:
            continue
        series_list.append(r)
        weights.append((h.market_value_cad or 0) / total_value)
    if not series_list:
        return PortfolioStats(risk_free_rate=risk_free)

    combined = pd.concat(series_list, axis=1).dropna(how="all")
    if combined.empty:
        return PortfolioStats(risk_free_rate=risk_free)
    combined = combined.fillna(0.0)
    w = np.array(weights)
    if w.sum() <= 0:
        w = np.ones(len(weights)) / len(weights)
    else:
        w = w / w.sum()

    weekly = (combined.values * w).sum(axis=1)
    if len(weekly) < 2:
        return PortfolioStats(risk_free_rate=risk_free)
    obs = len(weekly)
    avg = float(np.mean(weekly))
    std = float(np.std(weekly, ddof=1))
    total_return = float(np.prod(1 + weekly) - 1)
    annualized = (1 + avg) ** 52 - 1
    annualized_vol = std * math.sqrt(52)
    sharpe = ((annualized - risk_free) / annualized_vol) if annualized_vol > 0 else 0.0

    return PortfolioStats(
        max_periods_per_year=52,
        risk_free_rate=risk_free,
        observations=obs,
        avg_period_return=avg,
        std_dev_period=std,
        total_return=total_return,
        annualized_return=annualized,
        annualized_volatility=annualized_vol,
        sharpe_ratio=sharpe,
    )


def correlation_matrix(
    holdings: list[Holding] | None = None,
    account: str | None = None,
    period: str | None = None,
) -> CorrelationMatrix:
    """Pearson correlation of weekly returns across currently-held tickers.

    `account` restricts to a single account_number; `period` (1m/3m/.../all)
    filters the weekly-return series so the correlation reflects only the
    chosen window.

    Resilient on purpose: if anything goes wrong (no price history yet, a single
    ticker, all-NaN overlap, pandas oddities), we log and return an empty matrix
    instead of letting the API throw a 500.
    """
    import logging

    log = logging.getLogger(__name__)
    period_key = normalize_period(period)
    period_start = period_to_start_date(period_key) if period_key != "all" else None

    try:
        if holdings is None:
            txs = store.get_all_transactions()
            if account and account.lower() != "all":
                tabs = list_account_tabs()
                active = _resolve_active_tab(account, tabs)
                if active.account_number:
                    txs = [t for t in txs if t.account_number == active.account_number]
            holdings_acb, _ = compute_acb(txs)
            tickers = sorted({h.ticker for h in holdings_acb.values() if h.total_shares > 0})
        else:
            tickers = sorted({h.ticker for h in holdings})

        series: dict[str, pd.Series] = {}
        for ticker in tickers:
            df = store.get_price_history(ticker)
            r = _weekly_returns(df)
            if period_start is not None:
                r = r[r.index >= pd.Timestamp(period_start)]
            if not r.empty:
                series[ticker] = r

        # No history at all yet (fresh import): identity matrix for the tickers we know about.
        if not series:
            if not tickers:
                return CorrelationMatrix(tickers=[], matrix=[])
            n = len(tickers)
            identity = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
            return CorrelationMatrix(tickers=tickers, matrix=identity)

        # Only one ticker has history → degenerate; return its 1x1 self-correlation.
        if len(series) == 1:
            (only_t,) = series.keys()
            return CorrelationMatrix(tickers=[only_t], matrix=[[1.0]])

        df = pd.concat(series.values(), axis=1, keys=series.keys()).dropna(how="all")
        if df.empty or df.shape[1] < 2:
            return CorrelationMatrix(tickers=list(series.keys()), matrix=[[1.0]] if series else [])

        corr = df.corr().fillna(0.0)
        # pandas can return a read-only numpy view from .corr() — copy before
        # mutating, otherwise fill_diagonal raises ValueError.
        matrix = corr.values.copy()
        np.fill_diagonal(matrix, 1.0)
        return CorrelationMatrix(tickers=list(corr.columns), matrix=matrix.tolist())

    except Exception as e:
        log.exception("correlation_matrix failed: %s", e)
        return CorrelationMatrix(tickers=[], matrix=[])


def benchmark_history(start: str | None = None, ticker: str = "SPY") -> list[BenchmarkPoint]:
    """Return the benchmark ticker's weekly close history, normalized so the
    first point equals 100. SPY is the default (S&P 500 ETF).

    Triggers a yfinance fetch only if local history is missing/stale —
    same two-tier cache used for portfolio holdings.
    """
    try:
        market_data.ensure_history(ticker)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("benchmark history fetch failed: %s", e)

    df = store.get_price_history(ticker)
    if df.empty:
        return []
    weekly = _weekly_close(df)
    if start:
        try:
            weekly = weekly[weekly.index >= pd.Timestamp(start)]
        except Exception:
            pass
    if weekly.empty:
        return []
    base = float(weekly.iloc[0])
    if base <= 0:
        return []
    points: list[BenchmarkPoint] = []
    for idx, close in weekly.items():
        points.append(BenchmarkPoint(date=idx.date(), value=float(close) / base * 100.0))
    return points


def attribution_report(
    account: str | None = None, period: str | None = None
) -> AttributionReport:
    """Compute each holding's contribution to total portfolio return for the period.

    Contribution = gain_cad / portfolio_value_at_period_start × 100. With period
    "all" we use the first-known portfolio value as the baseline.
    """
    period_key = normalize_period(period)
    data = build_portfolio(account=account, period=period_key)
    usd_cad = data.exchange_rate.usd_cad or 1.0

    # Baseline: combined.period_start_value_cad when period is active, else the
    # earliest known portfolio value (so "All" still produces a meaningful chart).
    baseline = data.combined.period_start_value_cad
    if baseline <= 0:
        hist = portfolio_value_history(account=account)
        baseline = hist[0].total_cad if hist else 0.0

    rows: list[AttributionRow] = []
    for h in data.holdings:
        start_price = h.period_start_price
        current = h.current_price
        # For period=all with no start price, compare against ACB so we still
        # produce a number rather than 0.
        if start_price is None:
            start_price = h.acb_per_share if h.acb_per_share else None
        if start_price is None or current is None:
            continue
        gain_native = (current - start_price) * h.total_shares
        gain_cad = gain_native * usd_cad if h.currency == "USD" else gain_native
        contribution_pct = (gain_cad / baseline * 100) if baseline > 0 else 0.0
        rows.append(
            AttributionRow(
                ticker=h.ticker,
                account_type=h.account_type,
                security_name=h.security_name,
                shares=h.total_shares,
                period_start_price=start_price,
                current_price=current,
                currency=h.currency,
                gain_cad=round(gain_cad, 2),
                contribution_pct=round(contribution_pct, 3),
            )
        )

    rows.sort(key=lambda r: r.contribution_pct, reverse=True)
    top = rows[0] if rows else None
    drag = rows[-1] if rows and rows[-1].contribution_pct < 0 else None
    total_pct = sum(r.contribution_pct for r in rows)

    return AttributionReport(
        period=period_key,
        period_start_date=period_to_start_date(period_key) if period_key != "all" else None,
        total_return_pct=round(total_pct, 2),
        portfolio_period_start_cad=round(baseline, 2),
        rows=rows,
        top_contributor=f"{top.ticker} ({top.account_type})" if top else None,
        top_contributor_pct=top.contribution_pct if top else 0.0,
        biggest_drag=f"{drag.ticker} ({drag.account_type})" if drag else None,
        biggest_drag_pct=drag.contribution_pct if drag else 0.0,
    )


def dividend_report(account: str | None = None, period: str | None = None) -> DividendReport:
    """Aggregate dividend income from the transaction history.

    Produces:
      - monthly bar buckets (CAD-equivalent at the live FX rate)
      - upcoming projected payments based on each ticker's observed cadence
      - per-holding yield-on-cost (annual dividends / total cost)
      - trailing-12-month total and full-history annual average
      - period-scoped total when `period` is set (the trailing-12-month and
        yield-on-cost stay full-history per the plan — they have their own meaning)
    """
    from datetime import date as date_cls, timedelta

    txs = store.get_all_transactions()
    if account and account.lower() != "all":
        tabs = list_account_tabs()
        active = _resolve_active_tab(account, tabs)
        if active.account_number:
            txs = [t for t in txs if t.account_number == active.account_number]

    period_key = normalize_period(period)
    period_start = period_to_start_date(period_key) if period_key != "all" else None

    dividends = [t for t in txs if t.action == "DIVIDEND" and t.net_amount > 0]
    usd_cad, _ = market_data.get_fx("USDCAD")

    def to_cad(amount: float, currency: str) -> float:
        """Convert an amount in this ledger's currency to CAD using the live rate."""
        return amount * usd_cad if currency == "USD" else amount

    # Monthly buckets (every month from first dividend to current month, gaps as $0).
    monthly_map: dict[str, float] = defaultdict(float)
    for d in dividends:
        key = f"{d.transaction_date.year:04d}-{d.transaction_date.month:02d}"
        monthly_map[key] += to_cad(d.net_amount, d.currency)

    monthly: list[MonthlyDividend] = []
    if monthly_map:
        first_dt = min(d.transaction_date for d in dividends)
        today = date_cls.today()
        y, m = first_dt.year, first_dt.month
        while (y, m) <= (today.year, today.month):
            key = f"{y:04d}-{m:02d}"
            monthly.append(MonthlyDividend(month=key, amount_cad=round(monthly_map.get(key, 0.0), 2)))
            m += 1
            if m == 13:
                m = 1
                y += 1

    # Trailing 12 months
    cutoff_12mo = date_cls.today() - timedelta(days=365)
    trailing = sum(
        to_cad(d.net_amount, d.currency) for d in dividends if d.transaction_date >= cutoff_12mo
    )

    # Annual total: trailing-12mo if we have at least a year of history, else
    # scale up the partial history to a full year.
    if not dividends:
        annual_total = 0.0
    else:
        span_days = (date_cls.today() - min(d.transaction_date for d in dividends)).days or 1
        if span_days >= 365:
            annual_total = trailing
        else:
            total_so_far = sum(to_cad(d.net_amount, d.currency) for d in dividends)
            annual_total = total_so_far * 365 / span_days

    # Upcoming: per ticker, average days between past dividend payments and
    # project the next date. Cap to 6 most-likely-upcoming.
    upcoming: list[UpcomingDividend] = []
    by_ticker: dict[str, list[Transaction]] = defaultdict(list)
    for d in dividends:
        if d.resolved_ticker:
            by_ticker[d.resolved_ticker].append(d)

    today = date_cls.today()
    sec_names = _security_names(txs)
    for ticker, events in by_ticker.items():
        # Same-day dividends in multiple accounts (e.g. VEQT.TO paying both Margin
        # and TFSA on the same date) would otherwise produce a 0-day gap. Sum
        # same-date payments first, then compute the cadence on unique dates.
        events_sorted = sorted(events, key=lambda x: x.transaction_date)
        per_date_amount: dict = {}
        for ev in events_sorted:
            per_date_amount.setdefault(ev.transaction_date, []).append(ev)
        unique_dates = sorted(per_date_amount.keys())
        if len(unique_dates) < 2:
            continue  # not enough history to project a cadence
        gaps = [
            (unique_dates[i + 1] - unique_dates[i]).days
            for i in range(len(unique_dates) - 1)
        ]
        # Drop zero gaps defensively (shouldn't occur after the dedup above)
        gaps = [g for g in gaps if g > 0]
        if not gaps:
            continue
        gaps_sorted = sorted(gaps)
        median_gap = max(1, gaps_sorted[len(gaps_sorted) // 2])
        last_date = unique_dates[-1]
        next_date = last_date + timedelta(days=median_gap)
        while next_date < today:
            next_date = next_date + timedelta(days=median_gap)
        # Estimated amount = average of last three unique-date payments (CAD-eq).
        recent_dates = unique_dates[-3:]
        avg_amount = (
            sum(
                to_cad(ev.net_amount, ev.currency)
                for d in recent_dates
                for ev in per_date_amount[d]
            )
            / len(recent_dates)
        )
        upcoming.append(
            UpcomingDividend(
                ticker=ticker,
                security_name=sec_names.get(ticker),
                next_date=next_date,
                estimated_amount_cad=round(avg_amount, 2),
                cadence_days=median_gap,
            )
        )
    upcoming.sort(key=lambda u: u.next_date)
    upcoming = upcoming[:6]

    # Yield on cost per (ticker, account)
    holdings_acb, _ = compute_acb(txs)
    by_holding: list[DividendYieldRow] = []
    for (ticker, account_type), h in holdings_acb.items():
        if h.total_shares <= 0:
            continue
        # Sum dividends for THIS (ticker, account) — annualised similarly to total.
        ticker_divs = [
            d for d in dividends if d.resolved_ticker == ticker and d.account_type == account_type
        ]
        if not ticker_divs:
            continue
        first_div = min(d.transaction_date for d in ticker_divs)
        span = (today - first_div).days or 1
        total_div_cad = sum(to_cad(d.net_amount, d.currency) for d in ticker_divs)
        annual = total_div_cad if span >= 365 else total_div_cad * 365 / span
        cost_cad = h.total_cost * usd_cad if h.currency == "USD" else h.total_cost
        yoc = (annual / cost_cad * 100) if cost_cad > 0 else 0.0
        by_holding.append(
            DividendYieldRow(
                ticker=ticker,
                account_type=account_type,
                annual_dividends_cad=round(annual, 2),
                total_cost_cad=round(cost_cad, 2),
                yield_on_cost_pct=round(yoc, 3),
            )
        )
    by_holding.sort(key=lambda r: -r.annual_dividends_cad)

    period_total = 0.0
    if period_start is not None:
        period_total = sum(
            to_cad(d.net_amount, d.currency)
            for d in dividends
            if d.transaction_date >= period_start
        )

    return DividendReport(
        monthly=monthly,
        upcoming=upcoming,
        by_holding=by_holding,
        annual_total_cad=round(annual_total, 2),
        trailing_12mo_cad=round(trailing, 2),
        period_total_cad=round(period_total, 2),
        period_label=period_key,
    )


def portfolio_value_history(account: str | None = None, period: str | None = None) -> list[PortfolioValuePoint]:
    """Reconstruct weekly portfolio value from the transaction history.

    For each week from the first transaction to today:
      - holdings_value = Σ over (ticker, account) of shares_held_at_week × week_close_price
        (USD holdings converted to CAD at the live rate — historical FX would be
         more correct but requires daily BoC rates; live is the spec)
      - cash = Σ deposits − invested + dividends − fees − withdrawals, all dated ≤ week
      - net_deposits = Σ deposits + contributions, dated ≤ week
    """
    txs = store.get_all_transactions()
    if account and account.lower() != "all":
        tabs = list_account_tabs()
        active = _resolve_active_tab(account, tabs)
        if active.account_number:
            txs = [t for t in txs if t.account_number == active.account_number]

    if not txs:
        return []

    txs_sorted = sorted(txs, key=lambda t: t.transaction_date)
    first_date = txs_sorted[0].transaction_date

    # Build the set of tickers held (anywhere in history) so we know what
    # history series we need.
    tickers = sorted({t.resolved_ticker for t in txs_sorted if t.resolved_ticker and t.action in ("BUY", "SELL", "SPLIT")})

    # For each ticker, ensure we have history and grab the weekly close series.
    weekly_close: dict[str, pd.Series] = {}
    ticker_currency: dict[str, str] = {}
    for tk in tickers:
        try:
            market_data.ensure_history(tk)
        except Exception:
            pass
        df = store.get_price_history(tk)
        if df.empty:
            continue
        weekly_close[tk] = _weekly_close(df)
        # Currency: pick the first BUY's currency for this ticker (always consistent in practice).
        for t in txs_sorted:
            if t.resolved_ticker == tk and t.currency:
                ticker_currency[tk] = t.currency
                break

    if not weekly_close:
        return []

    # Live FX (single rate for the whole series).
    usd_cad, _ = market_data.get_fx("USDCAD")

    # Determine the week boundaries we'll report on — every Sunday from the
    # first transaction to today.
    today = pd.Timestamp(_now().date())
    start = pd.Timestamp(first_date) - pd.Timedelta(days=7)
    week_index = pd.date_range(start, today, freq="W")

    points: list[PortfolioValuePoint] = []
    for week_end in week_index:
        # Cumulative shares per (ticker) up to week_end
        shares: dict[str, float] = defaultdict(float)
        cash_cad = 0.0
        cash_usd = 0.0
        net_deposits_cad = 0.0
        net_deposits_usd = 0.0
        for t in txs_sorted:
            if pd.Timestamp(t.transaction_date) > week_end:
                break  # sorted, so no later txs match either
            if t.action == "BUY" and t.resolved_ticker:
                shares[t.resolved_ticker] += t.quantity
                if t.currency == "USD":
                    cash_usd += t.net_amount  # negative for buys
                else:
                    cash_cad += t.net_amount
            elif t.action == "SELL" and t.resolved_ticker:
                shares[t.resolved_ticker] -= abs(t.quantity)
                if t.currency == "USD":
                    cash_usd += t.net_amount  # positive for sells
                else:
                    cash_cad += t.net_amount
            elif t.action in ("DEPOSIT", "CONTRIBUTION"):
                if t.currency == "USD":
                    cash_usd += t.net_amount
                    net_deposits_usd += t.net_amount
                else:
                    cash_cad += t.net_amount
                    net_deposits_cad += t.net_amount
            elif t.action == "WITHDRAWAL":
                if t.currency == "USD":
                    cash_usd += t.net_amount  # already negative
                    net_deposits_usd += t.net_amount
                else:
                    cash_cad += t.net_amount
                    net_deposits_cad += t.net_amount
            elif t.action == "DIVIDEND":
                if t.currency == "USD":
                    cash_usd += t.net_amount
                else:
                    cash_cad += t.net_amount
            elif t.action == "FEE":
                if t.currency == "USD":
                    cash_usd -= abs(t.net_amount)
                else:
                    cash_cad -= abs(t.net_amount)

        # Holdings value at this week
        market_value_cad = 0.0
        for tk, qty in shares.items():
            if qty <= 0:
                continue
            series = weekly_close.get(tk)
            if series is None or series.empty:
                continue
            # Most-recent close ≤ week_end
            applicable = series[series.index <= week_end]
            if applicable.empty:
                continue
            close = float(applicable.iloc[-1])
            value_in_native = close * qty
            cur = ticker_currency.get(tk, "CAD")
            market_value_cad += value_in_native * usd_cad if cur == "USD" else value_in_native

        cash_in_cad = cash_cad + cash_usd * usd_cad
        net_deposits_in_cad = net_deposits_cad + net_deposits_usd * usd_cad
        total = market_value_cad + cash_in_cad

        # Skip the leading zeros before the user actually had any deposits
        if total == 0 and net_deposits_in_cad == 0:
            continue

        points.append(
            PortfolioValuePoint(
                date=week_end.date(),
                market_value_cad=round(market_value_cad, 2),
                cash_cad=round(cash_in_cad, 2),
                total_cad=round(total, 2),
                net_deposits_cad=round(net_deposits_in_cad, 2),
            )
        )

    # Period filter: keep one point at or just before period_start so the chart
    # starts cleanly at the boundary; otherwise the leading edge would jump.
    period_key = normalize_period(period)
    if period_key != "all" and points:
        period_start = period_to_start_date(period_key)
        prior = [p for p in points if p.date < period_start]
        within = [p for p in points if p.date >= period_start]
        if within:
            anchor = [prior[-1]] if prior else []
            points = anchor + within

    return points


def history_for(ticker: str) -> list[HistoricalDataPoint]:
    """Public form of weekly close history with weekly-return column attached."""
    df = store.get_price_history(ticker)
    if df.empty:
        return []
    s = _weekly_close(df)
    weekly_return = s.pct_change()
    points: list[HistoricalDataPoint] = []
    for idx, close in s.items():
        wr = weekly_return.loc[idx]
        points.append(
            HistoricalDataPoint(
                date=idx.date(),
                close=float(close),
                weekly_return=None if pd.isna(wr) else float(wr),
            )
        )
    return points
