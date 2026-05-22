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
from dataclasses import dataclass
from typing import Iterable

from backend import market_data
from backend.models import (
    Holding,
    RebalanceAction,
    RebalanceRequest,
    RebalanceResponse,
)
from backend.portfolio import build_portfolio


# Account types whose sells trigger taxable capital-gains events. Registered
# accounts (TFSA/RRSP/RESP/RRIF/FHSA/LIRA) are not subject to capital-gains tax
# in the usual sense and are excluded from the tax-warning surface.
TAXABLE_ACCOUNT_TYPES: frozenset[str] = frozenset({
    "Margin", "Non-Registered", "Individual",
    "IRA", "Roth IRA", "Traditional IRA",
    "Crypto", "Other",
})


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

    # First pass: compute desired shares per target. New positions (not currently
    # held) are supported — we look up the live price via market_data.
    @dataclass
    class _Draft:
        tgt_ticker: str
        tgt_account_type: str
        action_kind: str
        whole_shares: int
        price_native: float
        price_cad: float
        currency: str
        current_cad: float

    drafts: list[_Draft] = []
    warnings: list[str] = []

    for tgt in req.targets:
        key = (tgt.ticker, tgt.account_type)
        h = held.get(key)
        if h is None:
            # New position — fetch the live price from market_data.
            try:
                quote = market_data.get_quote(tgt.ticker)
            except Exception as e:
                warnings.append(f"{tgt.ticker}: live price unavailable ({e}); skipped.")
                continue
            if not quote or quote.price is None or quote.price <= 0:
                warnings.append(f"{tgt.ticker}: no live price available; skipped.")
                continue
            price_native = quote.price
            currency = quote.currency or "CAD"
            current_cad = 0.0
        else:
            if h.current_price is None or h.current_price <= 0:
                warnings.append(f"{tgt.ticker}: no live price; skipping.")
                continue
            price_native = h.current_price
            currency = h.currency
            current_cad = h.market_value_cad or 0.0

        price_cad = price_native * usd_cad if currency == "USD" else price_native
        if price_cad <= 0:
            continue

        target_cad = pool * (tgt.target_pct / 100.0)
        delta_cad = target_cad - current_cad

        if req.mode == "new_money" and delta_cad <= 0:
            # Buy-only mode skips over-weight / correctly-weighted positions.
            continue

        share_delta = delta_cad / price_cad
        whole_shares = math.floor(abs(share_delta))
        if whole_shares <= 0:
            continue
        action_kind = "BUY" if share_delta > 0 else "SELL"
        drafts.append(_Draft(
            tgt_ticker=tgt.ticker,
            tgt_account_type=tgt.account_type,
            action_kind=action_kind,
            whole_shares=whole_shares,
            price_native=price_native,
            price_cad=price_cad,
            currency=currency,
            current_cad=current_cad,
        ))

    # Budget / cash-neutrality enforcement.
    # In `new_money` mode, the sum of BUY cost_cad must not exceed new_money_cad.
    # In `rebalance` mode, sells must fund buys: ΣBUY ≤ ΣSELL + cash available.
    # Scale-down BUYs proportionally (floor to whole shares) when over budget.
    buys = [d for d in drafts if d.action_kind == "BUY"]
    sells = [d for d in drafts if d.action_kind == "SELL"]
    sells_cad = sum(d.whole_shares * d.price_cad for d in sells)
    if req.mode == "new_money":
        budget_cad = req.new_money_cad
    else:
        # In rebalance mode the budget is the sell proceeds; we don't auto-spend
        # the existing cash balance (that would silently transmute idle cash into
        # equity without the user asking).
        budget_cad = sells_cad

    buys_cad = sum(d.whole_shares * d.price_cad for d in buys)
    if buys_cad > budget_cad + 0.01 and buys_cad > 0:
        scale = budget_cad / buys_cad
        for d in buys:
            d.whole_shares = math.floor(d.whole_shares * scale)
        scaled_total = sum(d.whole_shares * d.price_cad for d in buys)
        warnings.append(
            f"Buy recommendations scaled down by {(1 - scale) * 100:.1f}% to stay within "
            f"the {('new-money budget' if req.mode == 'new_money' else 'sell proceeds')} of "
            f"${budget_cad:,.2f} (raw need was ${buys_cad:,.2f}; scaled to ${scaled_total:,.2f})."
        )
        # Drop any draft that scaled down to 0 shares.
        buys = [d for d in buys if d.whole_shares > 0]

    drafts = sells + buys

    # Cross-account warnings: if a target ticker exists in multiple account_types,
    # surface that the rebalancer is treating each (ticker, account_type) as its
    # own line — proceeds from a TFSA sell can't legally fund a Margin buy.
    accts_per_ticker: dict[str, set[str]] = {}
    for d in drafts:
        accts_per_ticker.setdefault(d.tgt_ticker, set()).add(d.tgt_account_type)
    multi_account = {t for t, accts in accts_per_ticker.items() if len(accts) > 1}
    for t in multi_account:
        warnings.append(
            f"{t} appears in multiple account types — sells from one account can't "
            f"fund buys in another (e.g. TFSA proceeds cannot pay for Margin buys). "
            f"Review each leg before executing."
        )

    # Cross-account funding warning: in `rebalance` mode, group sells and buys by
    # account_type and flag any account that has buys without enough same-account
    # sells to cover them. Each registered account is its own cash silo.
    if req.mode == "rebalance":
        sells_by_type: dict[str, float] = {}
        buys_by_type: dict[str, float] = {}
        for d in drafts:
            bucket = sells_by_type if d.action_kind == "SELL" else buys_by_type
            bucket[d.tgt_account_type] = bucket.get(d.tgt_account_type, 0.0) + d.whole_shares * d.price_cad
        for acct_type, buy_amt in buys_by_type.items():
            sell_amt = sells_by_type.get(acct_type, 0.0)
            if buy_amt > sell_amt + 0.01:
                warnings.append(
                    f"{acct_type}: recommended buys total ${buy_amt:,.2f} but same-account "
                    f"sells only total ${sell_amt:,.2f}. The gap of ${buy_amt - sell_amt:,.2f} "
                    f"must come from existing cash in this account or new contributions — "
                    f"proceeds from other account types cannot be transferred without "
                    f"triggering a withdrawal/contribution event."
                )

    # Per-leg post-check assertion to make the budget contract auditable.
    final_buys_cad = sum(d.whole_shares * d.price_cad for d in drafts if d.action_kind == "BUY")
    if req.mode == "new_money":
        assert final_buys_cad <= req.new_money_cad + 1.0, (
            f"Rebalancer exceeded new-money budget: ${final_buys_cad:.2f} > ${req.new_money_cad:.2f}"
        )

    # Materialise the actions.
    actions: list[RebalanceAction] = []
    for d in drafts:
        cost_cad = d.whole_shares * d.price_cad
        resulting_cad = (
            d.current_cad + cost_cad if d.action_kind == "BUY" else d.current_cad - cost_cad
        )
        resulting_pct = (resulting_cad / pool * 100.0) if pool > 0 else 0.0
        actions.append(
            RebalanceAction(
                action=d.action_kind,  # type: ignore[arg-type]
                ticker=d.tgt_ticker,
                account_type=d.tgt_account_type,
                shares=d.whole_shares,
                price=d.price_native,
                currency=d.currency,
                cost_cad=round(cost_cad, 2),
                resulting_pct=round(resulting_pct, 2),
            )
        )

    # Tax warning covers every taxable (non-registered) account type — not just
    # legacy "Margin". TFSA/RRSP/RESP/RRIF/FHSA/LIRA sells are non-taxable.
    note = None
    if any(a.action == "SELL" and a.account_type in TAXABLE_ACCOUNT_TYPES for a in actions):
        note = (
            "Selling in a taxable account may trigger capital gains. Where possible, "
            "rebalance via your TFSA or RRSP first."
        )

    return RebalanceResponse(
        actions=actions,
        warnings=warnings,
        target_total_pct=round(target_total, 2),
        portfolio_value_cad=round(total_holdings_cad, 2),
        note=note,
    )
