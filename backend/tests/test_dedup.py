"""Dedup tests — re-importing the same file must insert 0 new rows."""
from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEST_DATA = PROJECT_ROOT / "test_data"

from backend.parsers.registry import parse_with_registry
from backend.store import upsert_transactions


class TestDedup:
    def test_reimport_inserts_zero(self):
        ws_file = TEST_DATA / "csv" / "Wealthsimple_2024.csv"
        result = parse_with_registry(ws_file)
        txs = result.transactions
        assert len(txs) > 0

        first = upsert_transactions(txs)
        assert first.inserted == len(txs)

        second = upsert_transactions(txs)
        assert second.inserted == 0
        assert second.skipped_duplicates == len(txs)
        assert second.total_in_db == first.total_in_db
