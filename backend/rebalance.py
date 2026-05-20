"""Rebalancing advisor — translates target % allocations into buy/sell shares.

Two modes:
  - "rebalance":  freely sell over-weight positions and buy under-weight ones
                  until each holding hits its target.
  - "new_money":  buy-only. Distribute `new_money_cad` to push positions toward
                  their targets without selling anything.

All math runs in CAD using live prices. Shares are rounded DOWN to whole units
since the user can't transact fractional shares at most Canadian brokers.
"""
from __future__ import annotations

import math
from typing import Iterable

from backend import market_data
from backend.models import (
    Holding,
    RebalanceAction,
    RebalanceRequest,
    RebalanceResponse,
)
from backend.portfolio import build_portfolio


def compute_rebalance(req: RebalanceRequest) -> RebalanceResponse:
    """Produce buy/sell instructions for the active profile given the user's targets."""
    data = build_portfolio()
    usd_cad = data.exchange_rate.usd_cad or 1.0

    # Total target % must sum to 100 (allow rounding slop ± 0.5 %).
    target_total = sum(t.target_pct for t in req.targets)
    if abs(target_total - 100.0) > 0.5:
        return RebalanceResponse(
            actions=[],
            warnings=[
                f"Target percentages sum to {target_total:.2f}% — they must sum to 100% before rebalancing.",
            ],
            target_total_pct=round(target_total, 2),
            portfolio_value_cad=0.0,
        )

    # Holdings keyed by (ticker, account_type) for quick lookup.
    held: dict[tuple[str, str], Holding] = {(h.ticker, h.account_type): h for h in data.holdings}

    # Current portfolio value (excluding cash — we're allocating across holdings).
    total_holdings_cad = sum((h.market_value_cad or 0.0) for h in data.holdings)
    cash_cad = (
        data.combined.cash_remaining_cad
        + data.combined.cash_remaining_usd * usd_cad
    )

    # In rebalance mode the rebalance pool = current holdings value (we don't
    # spend the existing cash automatically). The user's "new money" option is
    # the explicit way to inject cash.
    if req.mode == "new_money":
        if req.new_money_cad <= 0:
            return RebalanceResponse(
                actions=[],
                warnings=["new_money_cad must be greater than 0 for new-money mode."],
                target_total_pct=round(target_total, 2),
                portfolio_value_cad=round(total_holdings_cad, 2),
            )
        pool = total_holdings_cad + req.new_money_cad
    else:
        pool = total_holdings_cad

    actions: list[RebalanceAction] = []
    warnings: list[str] = []

    for tgt in req.targets:
        key = (tgt.ticker, tgt.account_type)
        h = held.get(key)
        if h is None:
            warnings.append(
                f"{tgt.ticker} ({tgt.account_type}) is in the target list but not currently held — "
                f"add an initial buy manually for new positions."
            )
            continue
        if h.current_price is None or h.current_price <= 0:
            warnings.append(f"No live price for {tgt.ticker}; skipping.")
            continue

        target_cad = pool * (tgt.target_pct / 100.0)
        current_cad = h.market_value_cad or 0.0
        delta_cad = target_cad - current_cad

        # Convert delta back to shares of the native price.
        price_cad = h.current_price * usd_cad if h.currency == "USD" else h.current_price
        if price_cad <= 0:
            continue

        if req.mode == "new_money" and delta_cad <= 0:
            # Buy-only mode skips over-weight or correctly-weighted positions.
            continue

        share_delta = delta_cad / price_cad
        whole_shares = math.floor(abs(share_delta))
        if whole_shares <= 0:
            continue
        action_kind = "BUY" if share_delta > 0 else "SELL"
        cost_cad = whole_shares * price_cad
        resulting_cad = (
            current_cad + cost_cad if action_kind == "BUY" else current_cad - cost_cad
        )
        resulting_pct = (resulting_cad / pool * 100.0) if pool > 0 else 0.0

        actions.append(
            RebalanceAction(
                action=action_kind,  # type: ignore[arg-type]
                ticker=tgt.ticker,
                account_type=tgt.account_type,
                shares=whole_shares,
                price=h.current_price,
                currency=h.currency,
                cost_cad=round(cost_cad, 2),
                resulting_pct=round(resulting_pct, 2),
            )
        )

    note = None
    if any(a.action == "SELL" and a.account_type == "Margin" for a in actions):
        note = (
            "Selling in your Margin account may trigger capital gains. Where possible, "
            "rebalance via your TFSA or RRSP first."
        )

    return RebalanceResponse(
        actions=actions,
        warnings=warnings,
        target_total_pct=round(target_total, 2),
        portfolio_value_cad=round(total_holdings_cad, 2),
        note=note,
    )
