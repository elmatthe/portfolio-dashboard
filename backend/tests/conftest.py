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
    """Point the DB engine at a fresh temporary SQLite file for every test."""
    os.environ["PORTFOLIO_DB_PATH"] = str(tmp_path / "test_portfolio.db")
    os.environ.pop("PORTFOLIO_PROFILES_DIR", None)

    from backend import db
    db.reset_engine_for_tests()
    db.get_engine()
    yield
    db.reset_engine_for_tests()
    os.environ.pop("PORTFOLIO_DB_PATH", None)
