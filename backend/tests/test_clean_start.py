"""Item A — clean-machine startup regression.

The external tester's public v0.5.3 install hung forever on the splash because
the backend never became healthy on a clean box (and v0.5.3's always-on-top
splash masked the timeout dialog behind it — fixed in 0.6.x commit 3db14a5).

These tests pin the *backend* half of the contract the Electron splash polls:
starting from a completely empty profile directory (the real first-run
condition a clean machine presents), the backend must

  * initialise a brand-new default profile,
  * create the profile database on disk,
  * serve ``/health`` 200 with ``db_corrupt == False``, and
  * register every parser (a short registry list is the PyInstaller
    hidden-import regression that historically crashed packaged builds with
    ``KeyError: 'generic'``).

If any of these regress, ``/health`` would never return 200 and the splash
would sit on "Starting local data service…" — exactly the tester's symptom.

A second test pins Item A4: ``factory_reset`` must remove *all* top-level
app-generated artifacts (backend.log, window-state.json), not just the profile
databases, so a reset truly returns to a fresh-install state.
"""
from __future__ import annotations

from fastapi.testclient import TestClient


def _point_at_fresh_dir(tmp_path, monkeypatch):
    """Bind the backend to a pristine, empty profile dir (true first-run)."""
    profiles_dir = tmp_path / "FreshAppData"
    profiles_dir.mkdir()
    monkeypatch.setenv("PORTFOLIO_PROFILES_DIR", str(profiles_dir))
    monkeypatch.delenv("PORTFOLIO_DB_PATH", raising=False)

    from backend import db

    db.dispose_engine(reset_path=True)
    return profiles_dir


def test_clean_first_run_serves_health_200(tmp_path, monkeypatch):
    """A pristine profile dir must yield a healthy backend, not a hang."""
    profiles_dir = _point_at_fresh_dir(tmp_path, monkeypatch)

    from backend import db
    from backend.main import app

    # Entering the TestClient as a context manager runs the FastAPI lifespan —
    # the same profile-init + engine-bind the PyInstaller backend does on launch,
    # which is what the Electron /health poll is waiting on.
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["db_corrupt"] is False

    # First run must have materialised the manifest + a real profile DB on disk.
    assert (profiles_dir / "profiles.json").exists(), "first run left no profiles.json"
    dbs = list(profiles_dir.glob("profiles/*/portfolio.db"))
    assert dbs, "first run did not create a profile database"

    db.dispose_engine(reset_path=True)


def test_clean_start_registers_all_parsers():
    """A short registry list is the KeyError: 'generic' packaging regression."""
    from backend.parsers import BROKER_PARSERS

    assert "generic" in BROKER_PARSERS, "generic fallback parser missing"
    assert len(BROKER_PARSERS) >= 12, f"only {len(BROKER_PARSERS)} parsers registered"


def test_factory_reset_removes_top_level_artifacts(tmp_path, monkeypatch):
    """Item A4: reset must wipe backend.log / window-state.json, not just DBs."""
    profiles_dir = _point_at_fresh_dir(tmp_path, monkeypatch)

    from backend import db, profiles

    # Materialise a first-run profile, then drop the stray top-level files a real
    # run leaves alongside the profiles dir (Electron writes both of these).
    profiles.get_active_profile()
    (profiles_dir / "backend.log").write_text("stale log line\n", encoding="utf-8")
    (profiles_dir / "window-state.json").write_text("{}", encoding="utf-8")

    db.dispose_engine(reset_path=True)
    fresh = profiles.factory_reset()
    assert fresh is not None

    assert not (profiles_dir / "backend.log").exists(), "backend.log survived reset"
    assert not (profiles_dir / "window-state.json").exists(), "window-state.json survived reset"
    # …and a clean default profile manifest is back in place.
    assert (profiles_dir / "profiles.json").exists()

    # factory_reset() leaves DB materialisation to its caller (the /api/app/reset
    # endpoint rebinds the engine, which creates the file lazily). Mirror that
    # here to prove the full reset→recreate cycle lands a usable profile DB.
    db.set_db_path(profiles.profile_db_path(fresh.id))
    db.get_engine()
    dbs = list(profiles_dir.glob("profiles/*/portfolio.db"))
    assert dbs, "factory_reset + engine rebind did not recreate a profile database"

    db.dispose_engine(reset_path=True)
