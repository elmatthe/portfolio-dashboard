"""Canadian Adjusted Cost Basis engine.

CRA rules implemented:
  - ACB is tracked **per security per account** (TFSA and Margin are separate ledgers)
  - All transactions are processed in strict chronological order across accounts
  - Buy:  new_ACB_total = old_ACB_total + (qty * price) + |commission|
          new_ACB_per_share = new_ACB_total / new_total_shares
  - Sell: capital_gain = (sale_price * shares_sold) - (acb_per_share * shares_sold) - |commission|
          ACB per share is unchanged on a sell; only the share count drops.
  - Superficial loss rule: if shares of the same security are repurchased
    within 30 calendar days before OR after a sell-at-a-loss, the loss is
    denied. The denied amount is added to the ACB of the new lot.
  - TFSA / RRSP / RESP: gains tracked but flagged non-taxable.
  - Dividends do not affect ACB; we just sum them per (ticker, account).
  - Multi-currency: ACB is maintained in the security's native currency.
    CAD-equivalent values for tax reporting are layered on top via the
    historical Bank of Canada rate (caller supplies it through `fx_rate_for_date`).

Reference: tsiemens/acb and dwrpayne/portfolio per the build plan.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable, Iterable

from backend.models import (
    AcbHolding,
    AccountType,
    CapitalGainsReport,
    Currency,
    RealizedGain,
    SuperficialLossAdjustment,
    Transaction,
)


REGISTERED_ACCOUNTS: set[AccountType] = {"TFSA", "RRSP", "RESP"}


@dataclass
class _LedgerEntry:
    """Single sell event before superficial-loss adjudication."""

    ticker: str
    account_type: AccountType
    currency: Currency
    transaction_date: date
    shares_sold: float
    sale_price: float
    acb_per_share_at_sale: float
    commission: float
    gross_gain: float  # before superficial-loss denial


@dataclass
class _AcbLedger:
    """Mutable per-(ticker, account) state walked in chronological order."""

    ticker: str
    account_type: AccountType
    currency: Currency = "CAD"
    total_shares: float = 0.0
    total_cost: float = 0.0  # ACB-tracked cost basis in native currency
    total_commission_paid: float = 0.0
    dividends_received: float = 0.0
    realized: list[_LedgerEntry] = field(default_factory=list)
    sloss_adjustments: list[SuperficialLossAdjustment] = field(default_factory=list)

    @property
    def acb_per_share(self) -> float:
        """Current ACB per share for this ledger entry (total_cost / total_shares)."""
        if self.total_shares <= 1e-9:
            return 0.0
        return self.total_cost / self.total_shares


def compute(
    transactions: Iterable[Transaction],
    *,
    fx_rate_for_date: Callable[[date, str], float] | None = None,
    security_names: dict[str, str] | None = None,
) -> tuple[dict[tuple[str, str], AcbHolding], CapitalGainsReport]:
    """Walk transactions chronologically and return ACB state + capital-gains report.

    Parameters
    ----------
    transactions
        All normalized transactions across all accounts.
    fx_rate_for_date
        Optional callable `(trade_date, currency) -> rate_to_cad` used to
        translate realized gains to CAD for tax reporting. When omitted, the
        process-wide `FXService` singleton is used. The CAD-converted figures
        populate `RealizedGain.total_gain_cad` and the `*_cad` totals on the
        report — these are the authoritative numbers for CRA reporting.
    security_names
        Optional ticker → display-name map for nicer reports.

    Returns
    -------
    (holdings_by_key, report)
        holdings_by_key: (resolved_ticker, account_type) → AcbHolding
        report: aggregated CapitalGainsReport
    """
    if fx_rate_for_date is None:
        from backend.fx import get_fx_service
        _fx = get_fx_service()
        def fx_rate_for_date(d: date, currency: str) -> float:
            return _fx.rate_to_cad(currency, d)
    txs = sorted(_filter_relevant(transactions), key=_chronological_key)
    ledgers: dict[tuple[str, AccountType], _AcbLedger] = {}

    # Index of buys per (ticker, account) for superficial-loss lookups.
    buys_index: dict[tuple[str, AccountType], list[tuple[date, float]]] = defaultdict(list)

    for tx in txs:
        ticker = tx.resolved_ticker
        if not ticker:
            continue  # we drop dividends/cash with no resolvable security in the per-holding pass

        key = (ticker, tx.account_type)
        ledger = ledgers.setdefault(
            key,
            _AcbLedger(ticker=ticker, account_type=tx.account_type, currency=tx.currency),
        )
        ledger.currency = tx.currency  # last-seen wins; should be consistent per security

        if tx.action == "BUY":
            cost = abs(tx.quantity * tx.price)
            commission = abs(tx.commission or 0.0)
            ledger.total_cost += cost + commission
            ledger.total_shares += tx.quantity
            ledger.total_commission_paid += commission
            buys_index[key].append((tx.transaction_date, tx.quantity))

        elif tx.action == "SELL":
            shares_sold = abs(tx.quantity)
            if shares_sold <= 0 or ledger.total_shares <= 0:
                continue
            shares_sold = min(shares_sold, ledger.total_shares)
            acb_per_share = ledger.acb_per_share
            commission = abs(tx.commission or 0.0)
            sale_price = tx.price
            gross_gain = (sale_price - acb_per_share) * shares_sold - commission

            ledger.total_shares -= shares_sold
            ledger.total_cost -= acb_per_share * shares_sold
            if ledger.total_shares <= 1e-9:
                ledger.total_shares = 0.0
                ledger.total_cost = 0.0

            ledger.realized.append(
                _LedgerEntry(
                    ticker=ticker,
                    account_type=tx.account_type,
                    currency=tx.currency,
                    transaction_date=tx.transaction_date,
                    shares_sold=shares_sold,
                    sale_price=sale_price,
                    acb_per_share_at_sale=acb_per_share,
                    commission=commission,
                    gross_gain=gross_gain,
                )
            )

        elif tx.action == "DIVIDEND":
            ledger.dividends_received += tx.net_amount

        elif tx.action == "SPLIT":
            # Quantity carries the new share count delta. If qty > 0, treat as a
            # forward split: scale share count, ACB per share scales inversely.
            if tx.quantity and ledger.total_shares > 0:
                ratio_target = (ledger.total_shares + tx.quantity) / ledger.total_shares
                ledger.total_shares *= ratio_target
                # total_cost stays the same; only per-share value moves.

    # Pass 2: superficial-loss adjudication.
    # CRA: loss is denied when the *same* security is held (or re-bought) within
    # the 30-day window (before OR after the sell) AND the taxpayer still holds shares
    # at the end of that window. For simplicity (and matching tsiemens/acb's approach),
    # we trigger denial whenever a buy occurs within ±30 days of a loss sale.
    for ledger in ledgers.values():
        if not ledger.realized:
            continue
        all_buys = buys_index.get((ledger.ticker, ledger.account_type), [])
        for entry in ledger.realized:
            if entry.gross_gain >= 0:
                continue
            # CRA's 30-day superficial-loss window is inclusive of the sale date
            # itself — a same-day repurchase triggers denial. Previous behaviour
            # excluded `d == entry.transaction_date`, which under-reported the
            # adjustment for any user who sold-at-a-loss and re-bought the same
            # day (a classic tax-loss-harvesting mistake the engine should catch).
            window_start = entry.transaction_date - timedelta(days=30)
            window_end = entry.transaction_date + timedelta(days=30)
            qualifying_buys = [
                (d, q) for d, q in all_buys if window_start <= d <= window_end
            ]
            if not qualifying_buys:
                continue
            # Fraction of sold shares that get the denied-loss treatment, per CRA formula:
            #   min(shares_sold, shares_bought_in_window, shares_held_at_end_of_window)
            shares_bought_in_window = sum(q for _, q in qualifying_buys)
            denied_fraction = min(1.0, shares_bought_in_window / entry.shares_sold)
            denied_loss = abs(entry.gross_gain) * denied_fraction

            ledger.sloss_adjustments.append(
                SuperficialLossAdjustment(
                    transaction_date=entry.transaction_date,
                    ticker=entry.ticker,
                    denied_loss=denied_loss,
                    repurchase_date=qualifying_buys[0][0],
                    note=f"Loss denied; added back to ACB of repurchased shares ({denied_fraction:.0%} of loss).",
                )
            )

            # Add the denied loss back to the remaining ACB cost basis.
            ledger.total_cost += denied_loss
            entry.gross_gain += denied_loss  # final reported gain (less negative)

    # Convert to public Pydantic models.
    holdings: dict[tuple[str, str], AcbHolding] = {}
    for (ticker, account_type), ledger in ledgers.items():
        is_registered = account_type in REGISTERED_ACCOUNTS
        is_tfsa = account_type == "TFSA"

        realized_models: list[RealizedGain] = []
        for e in ledger.realized:
            taxable = not is_registered
            note = None
            sloss_for_this = sum(
                a.denied_loss for a in ledger.sloss_adjustments if a.transaction_date == e.transaction_date
            )
            # CAD-equivalent values at the transaction-date FX rate. CAD positions
            # always get rate 1.0; non-CAD positions go through the FX callable
            # (defaults to FXService).
            fx = fx_rate_for_date(e.transaction_date, e.currency) if e.currency != "CAD" else 1.0
            realized_models.append(
                RealizedGain(
                    transaction_date=e.transaction_date,
                    ticker=e.ticker,
                    security_name=(security_names or {}).get(e.ticker),
                    account_type=e.account_type,
                    shares_sold=e.shares_sold,
                    sale_price=e.sale_price,
                    acb_per_share=e.acb_per_share_at_sale,
                    gain_per_share=(e.sale_price - e.acb_per_share_at_sale),
                    total_gain=e.gross_gain,
                    total_gain_cad=round(e.gross_gain * fx, 2),
                    fx_rate_to_cad=fx,
                    commission=e.commission,
                    currency=e.currency,
                    taxable=taxable,
                    superficial_loss_adjustment=sloss_for_this,
                    notes=note,
                )
            )

        total_realized = sum(r.total_gain for r in realized_models)

        holdings[(ticker, account_type)] = AcbHolding(
            ticker=ticker,
            security_name=(security_names or {}).get(ticker),
            account_type=account_type,
            currency=ledger.currency,
            total_shares=round(ledger.total_shares, 6),
            acb_per_share=round(ledger.acb_per_share, 4),
            total_cost=round(ledger.total_cost, 2),
            total_commission=round(ledger.total_commission_paid, 2),
            dividends_received=round(ledger.dividends_received, 2),
            realized_gains=realized_models,
            total_realized_gain=round(total_realized, 2),
            superficial_loss_adjustments=ledger.sloss_adjustments,
            is_tfsa=is_tfsa,
            is_registered=is_registered,
        )

    # Aggregate report
    all_gains: list[RealizedGain] = []
    for h in holdings.values():
        all_gains.extend(h.realized_gains)

    total_taxable = sum(g.total_gain for g in all_gains if g.taxable)
    total_non_taxable = sum(g.total_gain for g in all_gains if not g.taxable)
    total_taxable_cad = sum((g.total_gain_cad or 0.0) for g in all_gains if g.taxable)
    total_non_taxable_cad = sum((g.total_gain_cad or 0.0) for g in all_gains if not g.taxable)
    total_sloss = sum(
        a.denied_loss for h in holdings.values() for a in h.superficial_loss_adjustments
    )
    # Superficial-loss CAD: each adjustment's currency follows the ledger that
    # produced it. Re-lookup the rate for the date.
    total_sloss_cad = 0.0
    for h in holdings.values():
        ccy = h.currency
        fx = fx_rate_for_date(date.today(), ccy) if ccy != "CAD" else 1.0
        for a in h.superficial_loss_adjustments:
            # Use the adjustment's transaction date if available.
            this_fx = fx_rate_for_date(a.transaction_date, ccy) if ccy != "CAD" else 1.0
            total_sloss_cad += a.denied_loss * this_fx

    report = CapitalGainsReport(
        realized_gains=sorted(all_gains, key=lambda g: g.transaction_date),
        total_taxable_gain=round(total_taxable, 2),
        total_non_taxable_gain=round(total_non_taxable, 2),
        total_taxable_gain_cad=round(total_taxable_cad, 2),
        total_non_taxable_gain_cad=round(total_non_taxable_cad, 2),
        total_superficial_loss_denied=round(total_sloss, 2),
        total_superficial_loss_denied_cad=round(total_sloss_cad, 2),
    )

    return holdings, report


def _filter_relevant(transactions: Iterable[Transaction]) -> list[Transaction]:
    """Drop rows that don't influence ACB (deposits, contributions, withdrawals)."""
    keep: set = {"BUY", "SELL", "DIVIDEND", "SPLIT", "FEE", "INTEREST"}
    return [t for t in transactions if t.action in keep]


def _chronological_key(tx: Transaction):
    """Sort key used to walk transactions in deposit/buy/dividend/sell order on each date."""
    # Stable sort: date first, then BUY before SELL on same day (so ACB is set before sale).
    order = {"BUY": 0, "SPLIT": 1, "DIVIDEND": 2, "SELL": 3}.get(tx.action, 9)
    return (tx.transaction_date, order, tx.hash)
