"""Shared fixtures for the backend test suite.

Each test session gets an isolated in-memory SQLite database so tests never
touch the real user data and never interfere with each other.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Ensure the project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

TEST_DATA = PROJECT_ROOT / "test_data"


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path):
    """Point the DB engine at a fresh temporary SQLite file for every test.

    Also isolates the profiles directory so factory_reset tests don't
    clobber dev data.
    """
    os.environ["PORTFOLIO_DB_PATH"] = str(tmp_path / "test_portfolio.db")
    os.environ["PORTFOLIO_PROFILES_DIR"] = str(tmp_path / "profiles")

    from backend import db
    db.dispose_engine(reset_path=True)
    db.get_engine()
    yield
    db.dispose_engine(reset_path=True)
    os.environ.pop("PORTFOLIO_DB_PATH", None)
    os.environ.pop("PORTFOLIO_PROFILES_DIR", None)
