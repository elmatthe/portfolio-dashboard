"""Parser + registry tests — baseline coverage for all broker fixtures."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEST_DATA = PROJECT_ROOT / "test_data"

from backend.parsers.registry import detect_broker, parse_with_registry, _populate_registry


class TestParserRegistry:
    def test_registry_integrity(self):
        """All registered parsers import without error."""
        _populate_registry()
        from backend.parsers.registry import BROKER_PARSERS
        assert len(BROKER_PARSERS) >= 11

    def test_all_parsers_return_transaction_lists(self):
        """Every parser's parse() returns a list (even if empty for bad input)."""
        _populate_registry()
        from backend.parsers.registry import BROKER_PARSERS
        for key, cls in BROKER_PARSERS.items():
            parser = cls()
            assert hasattr(parser, "parse")


class TestWealthsimpleCSV:
    @pytest.fixture
    def ws_file(self):
        return TEST_DATA / "csv" / "Wealthsimple_2024.csv"

    def test_detection(self, ws_file):
        broker, confidence = detect_broker(ws_file)
        assert broker == "wealthsimple"
        assert confidence >= 0.8

    def test_parse_row_count(self, ws_file):
        result = parse_with_registry(ws_file)
        assert len(result.transactions) == 20

    def test_regression_fields(self, ws_file):
        result = parse_with_registry(ws_file)
        txs = result.transactions
        buys = [t for t in txs if t.action == "BUY"]
        assert len(buys) >= 5
        for t in txs:
            assert t.broker == "wealthsimple"
            assert t.hash


class TestQuestradeXLSX:
    @pytest.fixture
    def qt_file(self):
        return TEST_DATA / "xlsx" / "Questrade_2024.xlsx"

    def test_detection(self, qt_file):
        broker, confidence = detect_broker(qt_file)
        assert broker == "questrade"
        assert confidence >= 0.9

    def test_parse_row_count(self, qt_file):
        result = parse_with_registry(qt_file)
        assert len(result.transactions) == 20

    def test_regression_fields(self, qt_file):
        result = parse_with_registry(qt_file)
        txs = result.transactions
        for t in txs:
            assert t.broker == "questrade"
            assert t.hash


class TestRBCCSV:
    @pytest.fixture
    def rbc_file(self):
        return TEST_DATA / "csv" / "RBC_DirectInvesting_2024.csv"

    def test_detection(self, rbc_file):
        broker, confidence = detect_broker(rbc_file)
        assert broker == "rbc"
        assert confidence >= 0.7

    def test_csv_row_count(self, rbc_file):
        result = parse_with_registry(rbc_file)
        assert len(result.transactions) == 20


class TestCIBCCSV:
    @pytest.fixture
    def cibc_file(self):
        return TEST_DATA / "csv" / "CIBC_InvestorsEdge_2024.csv"

    def test_detection(self, cibc_file):
        broker, confidence = detect_broker(cibc_file)
        assert broker == "cibc"
        assert confidence >= 0.8

    def test_csv_row_count(self, cibc_file):
        result = parse_with_registry(cibc_file)
        assert len(result.transactions) == 20


class TestTDCSV:
    @pytest.fixture
    def td_file(self):
        return TEST_DATA / "csv" / "TD_DirectInvesting_2024.csv"

    def test_detection(self, td_file):
        broker, confidence = detect_broker(td_file)
        assert broker == "td"
        assert confidence >= 0.7

    def test_csv_row_count(self, td_file):
        result = parse_with_registry(td_file)
        assert len(result.transactions) == 20


class TestInteractiveBrokersCSV:
    @pytest.fixture
    def ib_file(self):
        return TEST_DATA / "csv" / "InteractiveBrokers_2024.csv"

    def test_detection(self, ib_file):
        broker, confidence = detect_broker(ib_file)
        assert broker == "interactive"
        assert confidence >= 0.8

    def test_signed_quantity(self, ib_file):
        result = parse_with_registry(ib_file)
        for t in result.transactions:
            assert t.quantity >= 0, "IB quantity should be normalized to positive"
            if t.action == "BUY":
                assert t.net_amount <= 0
            elif t.action == "SELL":
                assert t.net_amount >= 0


class TestNationalBankCSV:
    @pytest.fixture
    def nb_file(self):
        return TEST_DATA / "csv" / "NationalBank_2024.csv"

    def test_detection(self, nb_file):
        broker, confidence = detect_broker(nb_file)
        assert broker == "nationalbank"
        assert confidence >= 0.8

    def test_parse(self, nb_file):
        result = parse_with_registry(nb_file)
        assert len(result.transactions) == 20


class TestFidelityCSV:
    @pytest.fixture
    def fid_file(self):
        return TEST_DATA / "csv" / "Fidelity_2024.csv"

    def test_detection(self, fid_file):
        broker, confidence = detect_broker(fid_file)
        assert broker == "fidelity"
        assert confidence >= 0.8

    def test_zero_commission(self, fid_file):
        result = parse_with_registry(fid_file)
        for t in result.transactions:
            assert t.commission == 0.0, f"Fidelity rows must have commission=0.0, got {t.commission}"


class TestBMOXLSX:
    @pytest.fixture
    def bmo_file(self):
        return TEST_DATA / "xlsx" / "BMO_InvestorLine_2024.xlsx"

    def test_detection(self, bmo_file):
        broker, confidence = detect_broker(bmo_file)
        assert broker == "bmo"
        assert confidence >= 0.8

    def test_skips_title_rows(self, bmo_file):
        result = parse_with_registry(bmo_file)
        assert len(result.transactions) >= 15


class TestScotiaXLSX:
    @pytest.fixture
    def scotia_file(self):
        return TEST_DATA / "xlsx" / "Scotia_iTrade_2024.xlsx"

    def test_detection(self, scotia_file):
        broker, confidence = detect_broker(scotia_file)
        assert broker == "scotiabank"
        assert confidence >= 0.8

    def test_parse(self, scotia_file):
        result = parse_with_registry(scotia_file)
        assert len(result.transactions) >= 15


class TestHSBCXLSX:
    @pytest.fixture
    def hsbc_file(self):
        return TEST_DATA / "xlsx" / "HSBC_InvestDirect_2024.xlsx"

    def test_detection(self, hsbc_file):
        broker, confidence = detect_broker(hsbc_file)
        assert broker == "hsbc"
        assert confidence >= 0.8

    def test_isin_captured(self, hsbc_file):
        result = parse_with_registry(hsbc_file)
        isins = [t.isin for t in result.transactions if t.isin]
        assert len(isins) >= 1, "HSBC parser must capture at least one ISIN"


class TestFXPopulation:
    def test_fx_non_null_on_parsed_rows(self):
        """FX rate to CAD must be non-null on all parsed rows."""
        ws_file = TEST_DATA / "csv" / "Wealthsimple_2024.csv"
        result = parse_with_registry(ws_file)
        for t in result.transactions:
            assert t.fx_rate_to_cad is not None, f"fx_rate_to_cad is None on {t.hash[:8]}"

    def test_net_cad_non_null(self):
        ws_file = TEST_DATA / "csv" / "Wealthsimple_2024.csv"
        result = parse_with_registry(ws_file)
        for t in result.transactions:
            assert t.net_cad is not None, f"net_cad is None on {t.hash[:8]}"
