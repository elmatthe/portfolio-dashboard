"""Profile integration tests (§4 / §5.4).

Each profile YAML enumerates a set of broker files and the assertions
that must hold after those files are imported. The runner loads them
sequentially via the parser registry and asserts against the expected
state.
"""
from __future__ import annotations

from glob import glob
from pathlib import Path

import pytest

from backend import store
from backend.parser import parse_file
from tests.conftest import TEST_DATA_DIR

try:
    import yaml  # PyYAML is optional; if missing we'll skip these tests.
except ImportError:
    yaml = None


PROFILE_DIR = Path(__file__).resolve().parent / "profiles"
PROFILE_FILES = sorted(glob(str(PROFILE_DIR / "*.yaml")))


def _load_profile(path: str) -> dict:
    if yaml is None:
        pytest.skip("PyYAML not installed")
    with open(path) as f:
        return yaml.safe_load(f)


@pytest.fixture
def project_root() -> Path:
    return TEST_DATA_DIR.parent


@pytest.mark.parametrize("profile_path", PROFILE_FILES)
def test_profile_loads(profile_path: str, project_root: Path):
    """Every profile imports without error and matches the expected counts."""
    profile = _load_profile(profile_path)
    inserted_total = 0
    brokers_seen: set[str] = set()
    all_txs = []
    for rel in profile["files"]:
        abs_path = project_root / rel
        assert abs_path.exists(), f"Missing fixture: {abs_path}"
        txs, fmt = parse_file(abs_path)
        brokers_seen.add(fmt.broker)
        all_txs.extend(txs)
        r = store.upsert_transactions(txs)
        inserted_total += r.inserted

    exp = profile["expected"]

    # Exact or floor count
    if "total_transactions" in exp:
        assert inserted_total == exp["total_transactions"], (
            f"{profile['name']}: inserted {inserted_total}, expected {exp['total_transactions']}"
        )
    if "total_transactions_min" in exp:
        assert inserted_total >= exp["total_transactions_min"]

    # Brokers
    if "brokers" in exp:
        assert set(exp["brokers"]).issubset(brokers_seen), (
            f"{profile['name']}: brokers seen {brokers_seen}, expected superset of {exp['brokers']}"
        )

    # Currencies floor
    if "currencies_at_least" in exp:
        seen_currencies = {t.currency for t in all_txs}
        missing = set(exp["currencies_at_least"]) - seen_currencies
        assert not missing, f"{profile['name']}: missing currencies {missing}"

    # Account types floor
    if "account_types_at_least" in exp:
        seen_types = {t.account_type for t in all_txs}
        missing = set(exp["account_types_at_least"]) - seen_types
        assert not missing, f"{profile['name']}: missing account types {missing}"

    # IB quantity sign normalisation
    if exp.get("has_normalized_quantities"):
        assert all(t.quantity >= 0 for t in all_txs)

    # ISIN presence (HSBC)
    if exp.get("has_isin"):
        assert any(t.isin for t in all_txs), f"{profile['name']}: no ISIN found"

    # Zero-commission floor (Fidelity)
    if "zero_commission_transactions_min" in exp:
        zeros = [t for t in all_txs if t.commission == 0.0]
        assert len(zeros) >= exp["zero_commission_transactions_min"]

    # Re-import dedup contract
    if "reimport_inserted" in exp:
        second_total = 0
        for rel in profile["files"]:
            txs, _ = parse_file(project_root / rel)
            r = store.upsert_transactions(txs)
            second_total += r.inserted
        assert second_total == exp["reimport_inserted"]
