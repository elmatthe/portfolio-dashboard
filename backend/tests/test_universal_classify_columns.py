"""Item 4 Step 3 — column classifier (alias + fuzzy + value profiling)."""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.import_engine.canonical import CanonicalField as F
from backend.import_engine.classify_columns import classify_columns, profile_column
from backend.import_engine.table_extract import ExtractedTable, extract, header_alias_hits

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEST_DATA = PROJECT_ROOT / "test_data"

NAMED_FIXTURES = [
    "csv/CIBC_InvestorsEdge_2024.csv",
    "csv/Fidelity_2024.csv",
    "csv/InteractiveBrokers_2024.csv",
    "csv/NationalBank_2024.csv",
    "csv/RBC_DirectInvesting_2024.csv",
    "csv/TD_DirectInvesting_2024.csv",
    "csv/Wealthsimple_2024.csv",
    "xlsx/BMO_InvestorLine_2024.xlsx",
    "xlsx/HSBC_InvestDirect_2024.xlsx",
    "xlsx/Questrade_2024.xlsx",
    "xlsx/Scotia_iTrade_2024.xlsx",
]


def _et(header, rows) -> ExtractedTable:
    return ExtractedTable(
        header=header,
        header_row_index=0,
        rows=rows,
        fmt="csv",
        matched_fields=header_alias_hits(header),
    )


# --------------------------------------------------------------------------- #
# Pass 1 — exact alias                                                         #
# --------------------------------------------------------------------------- #

def test_exact_alias_mapping():
    et = _et(
        ["Date", "Type", "Symbol", "Quantity", "Price", "Amount", "Currency"],
        [["2024-01-05", "Buy", "AAPL", "10", "180.00", "-1800.00", "USD"]],
    )
    r = classify_columns(et)
    assert r.mapping[F.TRANSACTION_DATE] == 0
    assert r.mapping[F.ACTION] == 1
    assert r.mapping[F.TICKER] == 2
    assert r.mapping[F.QUANTITY] == 3
    assert r.mapping[F.PRICE] == 4
    assert r.mapping[F.NET_AMOUNT] == 5
    assert r.mapping[F.CURRENCY] == 6
    assert all(m == "alias" for m in r.method_by_field.values())
    assert r.field_confidence[F.TRANSACTION_DATE] == 1.0
    assert r.overall_confidence > 0.8
    assert r.missing_required == []


# --------------------------------------------------------------------------- #
# Pass 2 — fuzzy (renamed header off by a word)                                #
# --------------------------------------------------------------------------- #

def test_fuzzy_renamed_header():
    # "Trade Commission" is not an exact alias of commission, but fuzzes high.
    et = _et(
        ["Trade Commission"],
        [["-9.95"], ["-9.95"], ["-4.95"]],
    )
    r = classify_columns(et)
    assert r.mapping.get(F.COMMISSION) == 0
    assert r.method_by_field[F.COMMISSION] == "fuzzy"
    assert 0.6 <= r.field_confidence[F.COMMISSION] <= 0.95


def test_fuzzy_does_not_beat_exact_for_same_column():
    # "Net Amount" is exact; a fuzzy contender must not override it.
    et = _et(["Net Amount"], [["100.00"], ["-50.00"]])
    r = classify_columns(et)
    assert r.mapping[F.NET_AMOUNT] == 0
    assert r.method_by_field[F.NET_AMOUNT] == "alias"


# --------------------------------------------------------------------------- #
# Pass 3 — value profiling resolves header-less columns                        #
# --------------------------------------------------------------------------- #

def test_value_profile_headerless_columns():
    # Opaque headers — only the VALUES reveal the fields.
    et = _et(
        ["Aaa", "Bbb", "Ccc"],
        [
            ["2024-01-05", "AAPL", "-1800.00"],
            ["2024-02-10", "MSFT", "-1950.00"],
            ["2024-03-15", "VEQT.TO", "45.00"],
            ["2024-04-01", "NVDA", "-600.00"],
        ],
    )
    r = classify_columns(et)
    assert r.mapping.get(F.TRANSACTION_DATE) == 0
    assert r.mapping.get(F.TICKER) == 1
    assert r.mapping.get(F.NET_AMOUNT) == 2
    assert r.method_by_field[F.TRANSACTION_DATE] == "profile"
    assert r.method_by_field[F.TICKER] == "profile"


def test_profile_column_detects_shapes():
    assert F.TRANSACTION_DATE in profile_column(["2024-01-01", "2024-02-02", "2024-03-03"])
    assert F.CURRENCY in profile_column(["USD", "CAD", "USD", "GBP"])
    assert F.ISIN in profile_column(["US0378331005", "CA9881131089", "GB0002634946"])


# --------------------------------------------------------------------------- #
# Invariant — no double mapping                                                #
# --------------------------------------------------------------------------- #

def test_no_double_map_invariant():
    # Two columns both alias to NET_AMOUNT; only one may win, the other is unmapped.
    et = _et(
        ["Amount", "Net Amount", "Symbol"],
        [["100", "100", "AAPL"], ["-50", "-50", "MSFT"]],
    )
    r = classify_columns(et)
    # One canonical field per column …
    assert len(set(r.mapping.values())) == len(r.mapping.values())
    # … and one column per field: NET_AMOUNT mapped exactly once.
    assert F.NET_AMOUNT in r.mapping
    losing_col = ({0, 1} - {r.mapping[F.NET_AMOUNT]}).pop()
    assert losing_col in r.unmapped_columns


# --------------------------------------------------------------------------- #
# MIN_SCHEMA enforcement                                                       #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("rel", NAMED_FIXTURES)
def test_min_schema_satisfied_on_real_fixtures(rel):
    r = classify_columns(extract(TEST_DATA / rel))
    assert r.missing_required == [], f"{rel}: unexpected gaps {r.missing_required}"
    assert r.overall_confidence > 0.5


def test_min_schema_flags_stripped_fixture_missing_date():
    # No date column at all → the date any_of group must be flagged missing.
    et = _et(
        ["Type", "Symbol", "Quantity", "Price"],
        [["Buy", "AAPL", "10", "180.00"], ["Sell", "MSFT", "5", "390.00"]],
    )
    r = classify_columns(et)
    assert any("transaction_date" in gap for gap in r.missing_required), r.missing_required
    # The transactional-signal group is still satisfied (ticker/quantity present).
    assert not any(gap.startswith("action|") for gap in r.missing_required)
