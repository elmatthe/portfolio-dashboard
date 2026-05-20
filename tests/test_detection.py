"""Auto-detection tests (§5.2). One row per fixture file."""
from __future__ import annotations

import pytest

from backend.parsers import detect_broker
from tests.conftest import f


@pytest.mark.parametrize("file,expected_broker", [
    ("RBC_DirectInvesting_2024.csv",            "rbc"),
    ("CIBC_InvestorsEdge_2024.csv",             "cibc"),
    ("TD_DirectInvesting_2024.csv",             "td"),
    ("BMO_InvestorLine_2024.csv",               "bmo"),
    ("Scotia_iTRADE_2024.csv",                  "scotiabank"),
    ("InteractiveBrokers_2024.csv",             "interactive"),
    ("NationalBank_DirectBrokerage_2024.csv",   "nationalbank"),
    ("Fidelity_2024.csv",                       "fidelity"),
    ("BMO_InvestorLine_2024.xlsx",              "bmo"),
    ("Scotia_iTRADE_2024.xlsx",                 "scotiabank"),
    ("HSBC_InvestDirect_2024.xlsx",             "hsbc"),
    ("RBC_DirectInvesting_2024.pdf",            "rbc"),
    ("TD_DirectInvesting_2024.pdf",             "td"),
    ("CIBC_InvestorsEdge_2024.pdf",             "cibc"),
    # Regression — must still detect correctly
    ("Wealthsimple_Test_Transactions.csv",      "wealthsimple"),
    ("Questrade_Test_Transactions.xlsx",        "questrade"),
])
def test_auto_detection(file: str, expected_broker: str):
    broker, confidence = detect_broker(f(file))
    assert broker == expected_broker, f"{file}: detected {broker} (conf {confidence:.2f})"
    assert confidence >= 0.5
