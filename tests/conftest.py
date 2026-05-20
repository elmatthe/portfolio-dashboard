"""Shared pytest fixtures.

Every test gets a fresh in-temp SQLite DB so dedup state from one test
doesn't bleed into another.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


TEST_DATA_DIR = Path(__file__).resolve().parent.parent / "test-transaction-reports"


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch, tmp_path):
    """Point the backend at a fresh temp DB for each test."""
    db_path = tmp_path / "portfolio.db"
    monkeypatch.setenv("PORTFOLIO_DB_PATH", str(db_path))
    # Force the engine to re-bind to this DB
    from backend import db
    db.reset_engine_for_tests()
    yield
    db.reset_engine_for_tests()


@pytest.fixture
def data_dir() -> Path:
    """Absolute path to test-transaction-reports/."""
    return TEST_DATA_DIR


def f(name: str) -> str:
    """Helper: full path string to a fixture file."""
    return str(TEST_DATA_DIR / name)
