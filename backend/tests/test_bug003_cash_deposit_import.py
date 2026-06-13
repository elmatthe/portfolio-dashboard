"""BUG-003 regression — generic import must persist ordinary cash funding rows.

A plain cash Deposit/Withdrawal (date + amount, no ticker, no quantity) was
classified PARTIAL and held back from persistence: "deposit" maps to the rich
TRANSFER_IN action, whose MIN_SCHEMA carried an UNCONDITIONAL
n_of=(2, (ticker, quantity)) — a contract only an in-kind security transfer can
meet. The funding side of an import silently vanished while the buys imported,
corrupting every net-deposit-based metric.

Fix: transfers now express their two alternative shapes via a conditional
`requires_if_present` clause — cash needs date + net_amount; the presence of a
TICKER is the evidence that selects the in-kind contract (quantity becomes
mandatory). Hard constraints verified here:

  - cash deposit / withdrawal (no ticker) persists as DEPOSIT / WITHDRAWAL
  - in-kind transfer with ticker + quantity still persists
  - a transfer row WITH a ticker but NO quantity stays PARTIAL (ambiguous
    journal/in-kind rows are never silently persisted as cash)
  - a BUY that is PARTIAL for a real reason stays PARTIAL
  - named fixtures still route to their named parsers (covered by the existing
    routing-invariant tests, re-run in the same suite)
"""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.import_engine.canonical import (
    CanonicalAction,
    CanonicalField,
    MIN_SCHEMA,
    requirement_gaps,
)
from backend.import_engine.diagnostics import pop_last_diagnostics
from backend.parsers.generic import GenericParser

_F = CanonicalField


def _write_csv(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# Schema level — requirement_gaps with the conditional transfer contract       #
# --------------------------------------------------------------------------- #

class TestTransferSchema:
    @pytest.mark.parametrize("action", [CanonicalAction.TRANSFER_IN, CanonicalAction.TRANSFER_OUT])
    def test_cash_shape_satisfies_schema(self, action):
        """date + net_amount alone (the audit's failing case) has no gaps."""
        mapped = {_F.TRANSACTION_DATE, _F.NET_AMOUNT}
        assert requirement_gaps(mapped, MIN_SCHEMA[action]) == []

    @pytest.mark.parametrize("action", [CanonicalAction.TRANSFER_IN, CanonicalAction.TRANSFER_OUT])
    def test_inkind_shape_satisfies_schema(self, action):
        """date + ticker + quantity (no net_amount) still supported."""
        mapped = {_F.TRANSACTION_DATE, _F.TICKER, _F.QUANTITY}
        assert requirement_gaps(mapped, MIN_SCHEMA[action]) == []

    @pytest.mark.parametrize("action", [CanonicalAction.TRANSFER_IN, CanonicalAction.TRANSFER_OUT])
    def test_ticker_without_quantity_gaps(self, action):
        """Ticker present selects the in-kind contract: quantity becomes
        mandatory even when a net_amount is also present (ambiguous rows are
        NOT silently treated as cash)."""
        mapped = {_F.TRANSACTION_DATE, _F.TICKER, _F.NET_AMOUNT}
        gaps = requirement_gaps(mapped, MIN_SCHEMA[action])
        assert gaps == ["quantity_with_ticker"]

    @pytest.mark.parametrize("action", [CanonicalAction.TRANSFER_IN, CanonicalAction.TRANSFER_OUT])
    def test_neither_shape_still_gaps(self, action):
        """Date alone (no amount, no ticker) is still unmet via any_of."""
        mapped = {_F.TRANSACTION_DATE}
        gaps = requirement_gaps(mapped, MIN_SCHEMA[action])
        assert gaps, "a transfer with neither amount nor security must gap"


# --------------------------------------------------------------------------- #
# End-to-end — the audit's exact repro through the generic parser              #
# --------------------------------------------------------------------------- #

class TestCashFundingPersists:
    def test_audit_repro_deposit_and_buy_both_persist(self, tmp_path):
        """The audit's repro CSV: the EUR deposit must import alongside the buy,
        as a DEPOSIT with a populated CAD equivalent."""
        f = _write_csv(
            tmp_path / "repro.csv",
            "Date,Action,Symbol,Quantity,Price,Amount,Currency,Account Type\n"
            "2024-06-01,Deposit,,0,0,10000,EUR,Margin\n"
            "2024-06-01,Buy,ZZEUR,100,100,-10000,EUR,Margin\n",
        )
        txs = GenericParser().parse(f)
        assert len(txs) == 2, f"expected deposit + buy, got {[t.action for t in txs]}"
        dep = next(t for t in txs if t.action == "DEPOSIT")
        buy = next(t for t in txs if t.action == "BUY")
        assert dep.net_amount == pytest.approx(10_000.0)
        assert dep.currency == "EUR"
        assert dep.net_cad == pytest.approx(14_800.0, abs=0.01)  # static EUR 1.48
        assert buy.raw_symbol == "ZZEUR"

        d = pop_last_diagnostics()
        assert d.state_counts.get("partial", 0) == 0
        assert d.persisted_rows == 2

    def test_cash_withdrawal_persists(self, tmp_path):
        f = _write_csv(
            tmp_path / "wd.csv",
            "Date,Action,Symbol,Quantity,Price,Amount,Currency,Account Type\n"
            "2024-03-01,Deposit,,,,5000,CAD,Margin\n"
            "2024-07-15,Withdrawal,,,,-2000,CAD,Margin\n",
        )
        txs = GenericParser().parse(f)
        actions = sorted(t.action for t in txs)
        assert actions == ["DEPOSIT", "WITHDRAWAL"]
        d = pop_last_diagnostics()
        assert d.state_counts.get("partial", 0) == 0

    def test_transfer_in_out_labels_cash_rows_persist(self, tmp_path):
        """'Transfer In'/'Transfer Out' labelled CASH rows (no ticker) behave
        like deposits/withdrawals — same root cause, same fix."""
        f = _write_csv(
            tmp_path / "xfer_cash.csv",
            "Date,Action,Symbol,Quantity,Price,Amount,Currency,Account Type\n"
            "2024-02-01,Transfer In,,,,7500,CAD,Margin\n"
            "2024-09-01,Transfer Out,,,,-1500,CAD,Margin\n",
        )
        txs = GenericParser().parse(f)
        actions = sorted(t.action for t in txs)
        assert actions == ["DEPOSIT", "WITHDRAWAL"]

    def test_preview_diagnostics_do_not_flag_cash_funding(self, tmp_path):
        """The four-state counts that /api/import/preview surfaces must not
        classify ordinary cash funding as needing manual repair."""
        f = _write_csv(
            tmp_path / "clean.csv",
            "Date,Action,Symbol,Quantity,Price,Amount,Currency,Account Type\n"
            "2024-06-01,Deposit,,,,10000,EUR,Margin\n",
        )
        txs = GenericParser().parse(f)
        assert len(txs) == 1 and txs[0].action == "DEPOSIT"
        d = pop_last_diagnostics()
        # The row imports cleanly: no partial/unmapped bucket, and no RowNote
        # flags it as needing repair (notes are only recorded for rows carrying
        # inference or gaps — pre-fix this row had a missing-fields note).
        assert d.state_counts.get("partial", 0) == 0
        assert d.state_counts.get("unmapped", 0) == 0
        assert d.state_counts.get("confident", 0) + d.state_counts.get("with_assumptions", 0) == 1
        assert all(not n.missing_fields for n in d.row_notes)


# --------------------------------------------------------------------------- #
# In-kind transfers and genuinely ambiguous / broken rows                      #
# --------------------------------------------------------------------------- #

class TestInKindAndAmbiguous:
    def test_security_transfer_with_ticker_and_quantity_persists(self, tmp_path):
        f = _write_csv(
            tmp_path / "inkind.csv",
            "Date,Action,Symbol,Quantity,Price,Amount,Currency,Account Type\n"
            "2024-01-05,Buy,AAPL,10,180.00,-1800.00,USD,Margin\n"
            "2024-04-10,Transfer In,VTI,25,,,USD,Margin\n",
        )
        txs = GenericParser().parse(f)
        xfer = [t for t in txs if t.raw_symbol == "VTI"]
        assert xfer, f"in-kind transfer should persist: {[(t.action, t.raw_symbol) for t in txs]}"
        assert xfer[0].action == "DEPOSIT"
        assert xfer[0].quantity == pytest.approx(25.0)

    def test_transfer_with_ticker_but_no_quantity_stays_partial(self, tmp_path):
        """A transfer carrying a ticker but no share count is ambiguous
        journal/in-kind data — held for review, never persisted as cash."""
        f = _write_csv(
            tmp_path / "ambiguous.csv",
            "Date,Action,Symbol,Quantity,Price,Amount,Currency,Account Type\n"
            "2024-01-05,Buy,AAPL,10,180.00,-1800.00,USD,Margin\n"
            "2024-04-10,Transfer In,VTI,,,9000,USD,Margin\n",
        )
        txs = GenericParser().parse(f)
        assert not any(t.raw_symbol == "VTI" for t in txs)

        d = pop_last_diagnostics()
        assert d.state_counts.get("partial", 0) >= 1
        partial = [n for n in d.row_notes if n.state == "partial"]
        assert any("quantity_with_ticker" in g for n in partial for g in n.missing_fields)

    def test_buy_partial_for_real_reason_stays_partial(self, tmp_path):
        """A BUY missing both quantity and price (and net) is still PARTIAL —
        the conditional-transfer fix must not loosen other actions' contracts."""
        f = _write_csv(
            tmp_path / "brokenbuy.csv",
            "Date,Action,Symbol,Quantity,Price,Amount,Currency,Account Type\n"
            "2024-01-05,Buy,AAPL,10,180.00,-1800.00,USD,Margin\n"
            "2024-02-10,Buy,MSFT,,,,USD,Margin\n",
        )
        txs = GenericParser().parse(f)
        assert not any(t.raw_symbol == "MSFT" for t in txs)
        d = pop_last_diagnostics()
        assert d.state_counts.get("partial", 0) >= 1
