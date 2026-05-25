"""ACB engine tests — verifies CRA-compliant cost basis, superficial loss, realized gains."""
from __future__ import annotations

from datetime import date

from backend.acb import compute
from backend.models import Transaction


def _make_tx(*, tx_date: str, action: str, ticker: str = "VEQT.TO",
             qty: float = 0.0, price: float = 0.0, commission: float = 0.0,
             net: float = 0.0, currency: str = "CAD",
             account_type: str = "TFSA", account_number: str = "test-1") -> Transaction:
    from backend.parser import compute_hash
    d = date.fromisoformat(tx_date)
    h = compute_hash(transaction_date=d, action=action, raw_symbol=ticker,
                     quantity=qty, net_amount=net, account_number=account_number)
    return Transaction(
        hash=h, broker="questrade", transaction_date=d, action=action,
        raw_symbol=ticker, resolved_ticker=ticker, quantity=qty, price=price,
        commission=commission, net_amount=net, currency=currency,
        account_number=account_number, account_type=account_type,
        fx_rate_to_cad=1.0, net_cad=net,
    )


def _fx_stub(d, c):
    return 1.0


class TestACBWalkOrder:
    def test_single_buy(self):
        txs = [_make_tx(tx_date="2024-01-10", action="BUY", qty=100, price=38.25, commission=9.95,
                        net=-3834.95)]
        holdings, report = compute(txs, fx_rate_for_date=_fx_stub)
        h = holdings[("VEQT.TO", "TFSA")]
        assert abs(h.total_cost - (100 * 38.25 + 9.95)) < 0.01
        assert h.total_shares == 100

    def test_two_buys_weighted_average(self):
        txs = [
            _make_tx(tx_date="2024-01-10", action="BUY", qty=100, price=38.25, commission=9.95,
                     net=-3834.95),
            _make_tx(tx_date="2024-02-10", action="BUY", qty=50, price=40.00, commission=9.95,
                     net=-2009.95),
        ]
        holdings, _ = compute(txs, fx_rate_for_date=_fx_stub)
        h = holdings[("VEQT.TO", "TFSA")]
        expected_cost = (100 * 38.25 + 9.95) + (50 * 40.00 + 9.95)
        assert abs(h.total_cost - expected_cost) < 0.01
        assert h.total_shares == 150
        assert abs(h.acb_per_share - expected_cost / 150) < 0.01

    def test_partial_sell_acb_unchanged(self):
        txs = [
            _make_tx(tx_date="2024-01-10", action="BUY", qty=100, price=40.00, commission=10.0,
                     net=-4010.00),
            _make_tx(tx_date="2024-03-10", action="SELL", qty=25, price=45.00, commission=10.0,
                     net=1115.00),
        ]
        holdings, report = compute(txs, fx_rate_for_date=_fx_stub)
        h = holdings[("VEQT.TO", "TFSA")]
        assert h.total_shares == 75
        acb_per_share = (100 * 40.00 + 10.0) / 100
        assert abs(h.acb_per_share - acb_per_share) < 0.01

    def test_full_sell_zeroes_out(self):
        txs = [
            _make_tx(tx_date="2024-01-10", action="BUY", qty=50, price=40.00, commission=10.0,
                     net=-2010.00),
            _make_tx(tx_date="2024-06-10", action="SELL", qty=50, price=45.00, commission=10.0,
                     net=2240.00),
        ]
        holdings, _ = compute(txs, fx_rate_for_date=_fx_stub)
        h = holdings[("VEQT.TO", "TFSA")]
        assert h.total_shares == 0.0
        assert h.total_cost == 0.0

    def test_realized_gain_correct(self):
        txs = [
            _make_tx(tx_date="2024-01-10", action="BUY", qty=100, price=40.00, commission=10.0,
                     net=-4010.00),
            _make_tx(tx_date="2024-06-10", action="SELL", qty=50, price=45.00, commission=10.0,
                     net=2240.00),
        ]
        holdings, report = compute(txs, fx_rate_for_date=_fx_stub)
        gains = report.realized_gains
        assert len(gains) == 1
        g = gains[0]
        acb_ps = (100 * 40.00 + 10.0) / 100
        expected_gain = (45.00 - acb_ps) * 50 - 10.0
        assert abs(g.total_gain - expected_gain) < 0.01

    def test_per_ticker_account_separation(self):
        txs = [
            _make_tx(tx_date="2024-01-10", action="BUY", qty=100, price=40.00,
                     account_type="TFSA"),
            _make_tx(tx_date="2024-01-10", action="BUY", qty=50, price=42.00,
                     account_type="Margin"),
        ]
        holdings, _ = compute(txs, fx_rate_for_date=_fx_stub)
        assert ("VEQT.TO", "TFSA") in holdings
        assert ("VEQT.TO", "Margin") in holdings
        assert holdings[("VEQT.TO", "TFSA")].total_shares == 100
        assert holdings[("VEQT.TO", "Margin")].total_shares == 50


class TestSuperficialLoss:
    def test_30_day_window_denies_loss(self):
        txs = [
            _make_tx(tx_date="2024-01-10", action="BUY", qty=100, price=40.00,
                     net=-4000.00),
            _make_tx(tx_date="2024-03-01", action="SELL", qty=50, price=35.00,
                     net=1750.00),
            _make_tx(tx_date="2024-03-15", action="BUY", qty=30, price=36.00,
                     net=-1080.00),
        ]
        holdings, report = compute(txs, fx_rate_for_date=_fx_stub)
        h = holdings[("VEQT.TO", "TFSA")]
        assert len(h.superficial_loss_adjustments) == 1
        assert h.superficial_loss_adjustments[0].denied_loss > 0

    def test_tfsa_sell_non_taxable(self):
        txs = [
            _make_tx(tx_date="2024-01-10", action="BUY", qty=100, price=40.00,
                     account_type="TFSA"),
            _make_tx(tx_date="2024-06-10", action="SELL", qty=50, price=45.00,
                     account_type="TFSA"),
        ]
        _, report = compute(txs, fx_rate_for_date=_fx_stub)
        for g in report.realized_gains:
            assert g.taxable is False
