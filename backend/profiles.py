"""Profile management — independent portfolios with isolated databases.

Layout:
    <profiles_dir>/
        profiles.json
        profiles/
            <profile_id>/portfolio.db

Switching profiles hot-swaps the SQLAlchemy engine in `backend.db` so all
subsequent reads/writes hit the new profile's DB. The Electron process does
NOT need to restart on a profile switch.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from backend._time import utcnow_naive as _now


logger = logging.getLogger(__name__)


DEFAULT_PROFILE_NAME = "My Portfolio"
DEFAULT_PROFILE_COLOR = "#3B82F6"


class Profile(BaseModel):
    id: str
    name: str
    created_at: datetime
    last_imported_at: datetime | None = None
    color: str = DEFAULT_PROFILE_COLOR


class ProfilesFile(BaseModel):
    active_profile_id: str
    profiles: list[Profile] = Field(default_factory=list)


# ---------- paths ----------

def profiles_dir() -> Path:
    """Top-level directory holding profiles.json + per-profile subfolders.

    Comes from PORTFOLIO_PROFILES_DIR (set by Electron to app.getPath('userData')).
    Falls back to ./data/ relative to the project root for development.
    """
    env = os.environ.get("PORTFOLIO_PROFILES_DIR")
    if env:
        p = Path(env)
    else:
        p = Path(__file__).resolve().parent.parent / "data"
    p.mkdir(parents=True, exist_ok=True)
    return p


def profiles_json_path() -> Path:
    """Path to the profiles manifest (profiles.json) inside the profiles dir."""
    return profiles_dir() / "profiles.json"


def profile_db_path(profile_id: str) -> Path:
    """Filesystem path to a specific profile's portfolio.db. Creates the parent dir if needed."""
    p = profiles_dir() / "profiles" / profile_id
    p.mkdir(parents=True, exist_ok=True)
    return p / "portfolio.db"


# ---------- load / save ----------

def load_profiles() -> ProfilesFile:
    """Read profiles.json. Auto-creates a default profile on first run."""
    path = profiles_json_path()
    if not path.exists():
        default = _create_default_profile_file()
        save_profiles(default)
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return ProfilesFile.model_validate(data)
    except Exception as e:
        logger.exception("profiles.json corrupt — rebuilding default: %s", e)
        default = _create_default_profile_file()
        save_profiles(default)
        return default


def save_profiles(state: ProfilesFile) -> None:
    """Serialise the profile manifest back to profiles.json."""
    path = profiles_json_path()
    path.write_text(
        state.model_dump_json(indent=2, exclude_none=False),
        encoding="utf-8",
    )


def _create_default_profile_file() -> ProfilesFile:
    """Build an in-memory ProfilesFile with a single auto-generated default profile."""
    pid = uuid.uuid4().hex[:8]
    return ProfilesFile(
        active_profile_id=pid,
        profiles=[
            Profile(
                id=pid,
                name=DEFAULT_PROFILE_NAME,
                created_at=_now(),
                color=DEFAULT_PROFILE_COLOR,
            )
        ],
    )


# ---------- mutations ----------

def create_profile(name: str, color: str = DEFAULT_PROFILE_COLOR) -> Profile:
    """Append a new profile to the manifest and return it."""
    state = load_profiles()
    name = (name or "").strip() or "New Profile"
    new = Profile(
        id=uuid.uuid4().hex[:8],
        name=name,
        created_at=_now(),
        color=color or DEFAULT_PROFILE_COLOR,
    )
    state.profiles.append(new)
    save_profiles(state)
    # Ensure the per-profile subdir exists (db file is created lazily by SQLAlchemy).
    profile_db_path(new.id)
    return new


def delete_profile(profile_id: str) -> dict:
    """Remove a profile + its data directory. Refuses to delete the last profile."""
    state = load_profiles()
    profile = _find_profile(state, profile_id)
    if profile is None:
        return {"success": False, "detail": "Profile not found"}

    if len(state.profiles) <= 1:
        return {
            "success": False,
            "detail": "Can't delete the last profile — create another first.",
        }

    state.profiles = [p for p in state.profiles if p.id != profile_id]
    # If we deleted the active profile, fall through to the first remaining one.
    if state.active_profile_id == profile_id:
        state.active_profile_id = state.profiles[0].id
    save_profiles(state)

    # Wipe the per-profile data directory.
    target = profiles_dir() / "profiles" / profile_id
    if target.exists():
        try:
            shutil.rmtree(target)
        except Exception as e:
            logger.warning("Could not remove profile dir %s: %s", target, e)

    return {"success": True, "active_profile_id": state.active_profile_id}


def activate_profile(profile_id: str) -> Profile:
    """Mark a profile as active in the manifest. Does NOT rebind the SQLAlchemy engine — caller does that."""
    state = load_profiles()
    profile = _find_profile(state, profile_id)
    if profile is None:
        raise KeyError(f"unknown profile {profile_id!r}")
    state.active_profile_id = profile_id
    save_profiles(state)
    return profile


def get_active_profile() -> Profile:
    """Read the currently-active profile, repairing the manifest if the pointer is stale."""
    state = load_profiles()
    p = _find_profile(state, state.active_profile_id)
    if p is None:
        # Defensive: active_profile_id points at a missing entry. Reset to first.
        if state.profiles:
            state.active_profile_id = state.profiles[0].id
            save_profiles(state)
            return state.profiles[0]
        # No profiles at all — create one and recurse.
        load_profiles()  # this triggers default creation
        return get_active_profile()
    return p


def mark_profile_imported(profile_id: str) -> None:
    """Stamp last_imported_at on a profile after a successful import."""
    state = load_profiles()
    p = _find_profile(state, profile_id)
    if p is None:
        return
    p.last_imported_at = _now()
    save_profiles(state)


def rename_profile(profile_id: str, new_name: str, new_color: str | None = None) -> Profile | None:
    """Change a profile's display name and/or accent color in place."""
    state = load_profiles()
    p = _find_profile(state, profile_id)
    if p is None:
        return None
    if new_name and new_name.strip():
        p.name = new_name.strip()
    if new_color:
        p.color = new_color
    save_profiles(state)
    return p


def _find_profile(state: ProfilesFile, profile_id: str) -> Profile | None:
    """Look up a profile by id within a ProfilesFile."""
    for p in state.profiles:
        if p.id == profile_id:
            return p
    return None
