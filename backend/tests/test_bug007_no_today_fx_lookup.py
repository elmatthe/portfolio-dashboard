"""BUG-007 regression — acb.compute() must never look up TODAY's FX rate.

The superficial-loss totals pass set `fx = fx_rate_for_date(date.today(), ccy)`
for every non-CAD holding and then never used it — a leftover from the
pre-BUG-002 code. Besides being dead work, it crashed compute() under any
strict date-keyed FX callable (one that only knows trade dates) even when the
portfolio had zero superficial-loss adjustments.

All rates the engine actually needs are transaction-date rates: the per-row
stored fx_rate_to_cad first, then the callable at the trade/adjustment date.
"""
from __future__ import annotations

from datetime import date

import pytest

from backend.acb import compute
from backend.models import Transaction
from backend.parser import compute_hash


def _tx(*, tx_date: str, action: str, ticker: str = "ZZUS", qty: float = 0.0,
        price: float = 0.0, net: float = 0.0, currency: str = "USD",
        fx: float | None = 1.30) -> Transaction:
    d = date.fromisoformat(tx_date)
    h = compute_hash(transaction_date=d, action=action, raw_symbol=ticker,
                     quantity=qty, net_amount=net, account_number="ACC-1")
    return Transaction(
        hash=h, broker="questrade", transaction_date=d, action=action,
        raw_symbol=ticker, resolved_ticker=ticker, quantity=qty, price=price,
        gross_amount=abs(net), commission=0, net_amount=net, currency=currency,
        account_number="ACC-1", account_type="Margin",
        fx_rate_to_cad=fx, net_cad=round(net * fx, 2) if fx is not None else None,
    )


def _strict_fx(known: dict[tuple[str, str], float]):
    """A date-keyed FX callable that raises KeyError for any (date, ccy) it
    was not explicitly given — the audit's repro condition."""
    def lookup(d: date, currency: str) -> float:
        return known[(d.isoformat(), currency)]
    return lookup


class TestNoTodayLookup:
    def test_no_adjustments_never_requests_todays_rate(self):
        """A plain foreign BUY (row carries its own FX) with zero superficial
        losses must compute without consulting the callable at all — pre-fix
        this raised KeyError on the unused date.today() lookup."""
        txs = [_tx(tx_date="2024-03-01", action="BUY", qty=100, price=10.0, net=-1000.0)]
        holdings, report = compute(txs, fx_rate_for_date=_strict_fx({}))
        assert holdings[("ZZUS", "Margin")].total_shares == pytest.approx(100.0)
        assert report.total_superficial_loss_denied_cad == 0.0

    def test_superficial_loss_portfolio_needs_no_today_rate(self):
        """Even WITH a denied loss, the engine computes the CAD denial from the
        CAD ledger (denied_loss_cad is set), so a strict callable that knows
        no dates at all still succeeds — every row carries fx_rate_to_cad."""
        txs = [
            _tx(tx_date="2024-03-01", action="BUY", qty=100, price=10.0, net=-1000.0),
            _tx(tx_date="2024-04-01", action="SELL", qty=50, price=8.0, net=400.0),
            _tx(tx_date="2024-04-10", action="BUY", qty=50, price=8.0, net=-400.0),
        ]
        holdings, report = compute(txs, fx_rate_for_date=_strict_fx({}))
        assert report.total_superficial_loss_denied > 0  # the loss was denied
        assert report.total_superficial_loss_denied_cad > 0
