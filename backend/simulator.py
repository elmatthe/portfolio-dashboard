"""Pure read-only "what-if" simulations.

All three modes (buy / sell / lump-sum) return a SimulationResult and write
nothing to the database. The user's actual position state is untouched.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from backend import market_data, store
from backend.acb import compute as compute_acb
from backend.models import (
    AccountType,
    SimulationResult,
)
from backend.portfolio import build_portfolio


def simulate_buy(ticker: str, shares: float, account_type: AccountType) -> SimulationResult:
    """Project the impact of buying `shares` of `ticker` today into account_type."""
    data = build_portfolio()
    usd_cad = data.exchange_rate.usd_cad or 1.0
    quote = market_data.get_quote(ticker)
    if quote.price is None:
        return SimulationResult(
            mode="buy",
            ticker=ticker,
            description=f"No live price available for {ticker} — cannot simulate.",
        )
    price = quote.price
    currency = quote.currency or "CAD"
    cost_native = price * shares
    cost_cad = cost_native * usd_cad if currency == "USD" else cost_native

    # If user already holds this in the account, blend ACB.
    existing = next(
        (h for h in data.holdings if h.ticker == ticker and h.account_type == account_type),
        None,
    )
    if existing:
        new_total_shares = existing.total_shares + shares
        new_total_cost = existing.total_cost + cost_native
        new_acb = new_total_cost / new_total_shares if new_total_shares > 0 else 0.0
        dividends_per_share = (
            (existing.dividends_received / existing.total_shares)
            if existing.total_shares > 0
            else 0.0
        )
    else:
        new_total_shares = shares
        new_acb = price  # first buy ignores commission for the simulation
        dividends_per_share = 0.0

    new_market_value_cad = (
        new_total_shares * price * (usd_cad if currency == "USD" else 1.0)
    )
    total_equity_after_cad = (
        data.combined.total_equity_cad + data.combined.total_equity_usd * usd_cad + cost_cad
    )
    new_allocation_pct = (
        new_market_value_cad / total_equity_after_cad * 100
        if total_equity_after_cad > 0
        else 0.0
    )
    projected_annual_dividends_cad = dividends_per_share * shares * (
        usd_cad if currency == "USD" else 1.0
    )

    lines = [
        f"Buy {shares:g} × {ticker} @ {price:.2f} {currency} = {cost_cad:,.2f} CAD cost",
        f"New position: {new_total_shares:g} shares · new ACB ≈ {new_acb:,.4f} {currency}/share",
        f"Allocation after this trade: {new_allocation_pct:.2f}% of portfolio",
    ]
    if projected_annual_dividends_cad > 0:
        lines.append(
            f"Projected annual dividends added: ~{projected_annual_dividends_cad:,.2f} CAD"
        )

    return SimulationResult(
        mode="buy",
        ticker=ticker,
        description=(
            f"Buying {shares:g} {ticker} in {account_type} → "
            f"{new_market_value_cad:,.0f} CAD position ({new_allocation_pct:.1f}% of portfolio)"
        ),
        detail_lines=lines,
        new_shares=new_total_shares,
        new_acb_per_share=round(new_acb, 4),
        new_market_value_cad=round(new_market_value_cad, 2),
        new_allocation_pct=round(new_allocation_pct, 2),
        projected_annual_dividends_cad=round(projected_annual_dividends_cad, 2),
    )


def simulate_sell(ticker: str, shares: float, account_type: AccountType) -> SimulationResult:
    """Project the gain/loss + tax owing from selling `shares` of `ticker`."""
    data = build_portfolio()
    settings = store.get_settings()
    quote = market_data.get_quote(ticker)
    existing = next(
        (h for h in data.holdings if h.ticker == ticker and h.account_type == account_type),
        None,
    )
    if existing is None:
        return SimulationResult(
            mode="sell",
            ticker=ticker,
            description=f"You don't currently hold {ticker} in {account_type}.",
        )
    if quote.price is None:
        return SimulationResult(
            mode="sell",
            ticker=ticker,
            description=f"No live price available for {ticker} — cannot simulate.",
        )
    if shares > existing.total_shares:
        return SimulationResult(
            mode="sell",
            ticker=ticker,
            description=(
                f"You only hold {existing.total_shares:g} shares of {ticker} in {account_type}."
            ),
        )

    price = quote.price
    currency = existing.currency
    usd_cad = data.exchange_rate.usd_cad or 1.0
    proceeds_native = price * shares
    acb_native = existing.acb_per_share * shares
    gain_native = proceeds_native - acb_native
    gain_cad = gain_native * usd_cad if currency == "USD" else gain_native

    is_registered = account_type in ("TFSA", "RRSP", "RESP")
    tax_estimate_cad = (
        0.0
        if is_registered
        else max(0.0, gain_cad) * 0.5 * settings.marginal_tax_rate
    )

    remaining_shares = existing.total_shares - shares
    remaining_native = remaining_shares * price
    remaining_cad = remaining_native * (usd_cad if currency == "USD" else 1.0)

    lines = [
        f"Sell {shares:g} × {ticker} @ {price:.2f} {currency}",
        f"Proceeds: {proceeds_native:,.2f} {currency} ({proceeds_native * (usd_cad if currency=='USD' else 1):,.2f} CAD)",
        f"ACB at sale: {existing.acb_per_share:,.4f} × {shares:g} = {acb_native:,.2f} {currency}",
        f"Capital {'gain' if gain_cad >= 0 else 'loss'}: {gain_cad:+,.2f} CAD",
    ]
    if is_registered:
        lines.append(f"{account_type} — non-taxable. No tax owing.")
    else:
        lines.append(
            f"50% inclusion @ {settings.marginal_tax_rate*100:.0f}% marginal rate "
            f"→ ~{tax_estimate_cad:,.2f} CAD tax"
        )
    lines.append(
        f"Remaining: {remaining_shares:g} shares · {remaining_cad:,.2f} CAD market value"
    )

    return SimulationResult(
        mode="sell",
        ticker=ticker,
        description=(
            f"Selling {shares:g} {ticker} ({account_type}) → "
            f"{gain_cad:+,.2f} CAD capital {'gain' if gain_cad >= 0 else 'loss'}"
        ),
        detail_lines=lines,
        capital_gain_cad=round(gain_cad, 2),
        tax_estimate_cad=round(tax_estimate_cad, 2),
        remaining_shares=remaining_shares,
        remaining_market_value_cad=round(remaining_cad, 2),
    )


def simulate_lump_sum(ticker: str, amount_cad: float, invest_date: date) -> SimulationResult:
    """What would $X invested in `ticker` on `invest_date` be worth today?"""
    if amount_cad <= 0:
        return SimulationResult(
            mode="lump_sum",
            ticker=ticker,
            description="Investment amount must be greater than 0.",
        )
    # Ensure history then look up the close on invest_date.
    try:
        market_data.ensure_history(ticker)
    except Exception:
        pass
    df = store.get_price_history(ticker)
    if df.empty:
        return SimulationResult(
            mode="lump_sum",
            ticker=ticker,
            description=f"No price history available for {ticker}.",
        )

    ts = pd.Timestamp(invest_date)
    earlier = df[df.index <= ts]
    if earlier.empty:
        return SimulationResult(
            mode="lump_sum",
            ticker=ticker,
            description=f"No data for {ticker} on or before {invest_date}.",
        )
    historic_close = float(earlier["close"].iloc[-1])
    if historic_close <= 0:
        return SimulationResult(
            mode="lump_sum",
            ticker=ticker,
            description=f"Bad historical price for {ticker} on {invest_date}.",
        )

    current_close = float(df["close"].iloc[-1])
    quote = market_data.get_quote(ticker)
    usd_cad, _ = market_data.get_fx("USDCAD")
    # If ticker is USD-denominated convert both ends to CAD.
    is_usd = ticker.upper().endswith(("AAPL", "VOO", "SPY")) or not (
        ticker.endswith(".TO") or ticker.endswith(".V") or ticker.endswith(".NE")
    )
    fx = usd_cad if is_usd else 1.0

    shares_bought = amount_cad / (historic_close * fx)
    value_today_native = shares_bought * (quote.price or current_close)
    value_today_cad = value_today_native * fx

    days = (date.today() - invest_date).days
    if days <= 0:
        annualised = None
    else:
        years = days / 365.25
        ratio = value_today_cad / amount_cad
        annualised = (ratio ** (1 / years) - 1) * 100 if ratio > 0 else None

    # Cash alternative: same dollars left in a HISA at the risk-free rate.
    settings = store.get_settings()
    rate = settings.risk_free_rate
    years = days / 365.25 if days > 0 else 0
    cash_alternative = amount_cad * ((1 + rate) ** years)

    lines = [
        f"Invest {amount_cad:,.2f} CAD in {ticker} on {invest_date.isoformat()}",
        f"Historical close that day: {historic_close:.2f} → {shares_bought:.2f} shares purchased",
        f"Today's value: {value_today_cad:,.2f} CAD",
        f"Cash held instead (at {rate*100:.2f}% HISA): {cash_alternative:,.2f} CAD",
    ]
    if annualised is not None:
        lines.append(f"Annualised return: {annualised:+.2f}% / yr over {days/365.25:.1f} years")

    return SimulationResult(
        mode="lump_sum",
        ticker=ticker,
        description=(
            f"{amount_cad:,.0f} CAD into {ticker} on {invest_date} → "
            f"{value_today_cad:,.0f} CAD today"
            + (f" ({annualised:+.1f}% / yr)" if annualised is not None else "")
        ),
        detail_lines=lines,
        value_today_cad=round(value_today_cad, 2),
        cash_alternative_cad=round(cash_alternative, 2),
        annualised_return_pct=round(annualised, 2) if annualised is not None else None,
    )
