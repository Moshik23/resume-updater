"""Fixed list of named profiles this tool is shared between.

Not a real multi-tenant account system -- there's no signup/login beyond the
single shared site password (app/auth.py). Profiles just partition each
person's default resume and application tracker so a small, known group of
people (not the general public) don't overwrite each other's data.
"""

import json

from app import storage
from app.models import TrackerEntry

PROFILES = ["moshik", "indhu", "guest"]

PROFILE_LABELS = {
    "moshik": "Moshik",
    "indhu": "Indhu",
    "guest": "Guest",
}


def is_valid_profile(profile: str) -> bool:
    return profile in PROFILES


def default_resume_meta(profile: str) -> dict:
    if not storage.profile_exists(profile, "default_resume_filename.txt"):
        return {"exists": False, "filename": None}
    filename = storage.load_profile_bytes(profile, "default_resume_filename.txt").decode("utf-8")
    return {"exists": True, "filename": filename}


def save_default_resume(profile: str, filename: str, source_format: str, data: bytes) -> None:
    storage.save_profile_bytes(profile, f"default_resume.{source_format}", data)
    storage.save_profile_bytes(profile, "default_resume_format.txt", source_format.encode("utf-8"))
    storage.save_profile_bytes(profile, "default_resume_filename.txt", filename.encode("utf-8"))


def load_default_resume(profile: str) -> tuple[bytes, str]:
    """Returns (data, source_format). Raises FileNotFoundError-ish KeyError if none saved."""
    source_format = storage.load_profile_bytes(profile, "default_resume_format.txt").decode("utf-8")
    data = storage.load_profile_bytes(profile, f"default_resume.{source_format}")
    return data, source_format


def load_tracker(profile: str) -> list[dict]:
    if not storage.profile_exists(profile, "tracker.json"):
        return []
    return json.loads(storage.load_profile_bytes(profile, "tracker.json").decode("utf-8"))


def append_tracker_entry(profile: str, entry: TrackerEntry) -> None:
    entries = load_tracker(profile)
    entries.append(entry.model_dump())
    storage.save_profile_bytes(profile, "tracker.json", json.dumps(entries).encode("utf-8"))
