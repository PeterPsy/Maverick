"""Workspace-owned Speech metadata and settings store."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from models import (
    DEFAULT_SYNTHESIS_ENGINE,
    DEFAULT_SYNTHESIS_LANGUAGE,
    DEFAULT_TRANSCRIPTION_ENGINE,
    DEFAULT_TRANSCRIPTION_PROFILE,
)

MAX_JOBS = 100
SETTINGS_SCHEMA_VERSION = "1"
DEFAULT_SETTINGS = {
    "schema_version": SETTINGS_SCHEMA_VERSION,
    "synthesis_engine": DEFAULT_SYNTHESIS_ENGINE,
    "synthesis_language": DEFAULT_SYNTHESIS_LANGUAGE,
    "transcription_engine": DEFAULT_TRANSCRIPTION_ENGINE,
    "transcription_profile": DEFAULT_TRANSCRIPTION_PROFILE,
}


def jobs_path(data_root: Path) -> Path:
    return data_root / "jobs.json"


def read_jobs(data_root: Path) -> dict:
    path = jobs_path(data_root)
    if not path.exists():
        return {"schema_version": "1", "jobs": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"schema_version": "1", "jobs": []}
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        return {"schema_version": "1", "jobs": []}
    return {"schema_version": str(payload.get("schema_version") or "1"), "jobs": payload["jobs"]}


def append_job(data_root: Path, job: dict) -> None:
    data_root.mkdir(parents=True, exist_ok=True)
    path = jobs_path(data_root)
    with _locked_file(data_root / ".jobs.lock"):
        payload = read_jobs(data_root)
        jobs = [job, *payload["jobs"]]
        payload["schema_version"] = "1"
        payload["jobs"] = jobs[:MAX_JOBS]
        _atomic_write_json(path, payload)


def upsert_job(data_root: Path, job: dict) -> None:
    """Insert or replace one bounded metadata job by job id."""
    data_root.mkdir(parents=True, exist_ok=True)
    path = jobs_path(data_root)
    job_id = str(job.get("job_id") or "")
    with _locked_file(data_root / ".jobs.lock"):
        payload = read_jobs(data_root)
        existing = next(
            (
                item
                for item in payload["jobs"]
                if isinstance(item, dict) and str(item.get("job_id") or "") == job_id
            ),
            {},
        )
        jobs = [item for item in payload["jobs"] if not isinstance(item, dict) or str(item.get("job_id") or "") != job_id]
        merged = {**existing, **job}
        if existing.get("created_at"):
            merged["created_at"] = existing["created_at"]
            merged["updated_at"] = job.get("created_at")
        payload["schema_version"] = "1"
        payload["jobs"] = [merged, *jobs][:MAX_JOBS]
        _atomic_write_json(path, payload)


def settings_path(data_root: Path) -> Path:
    return data_root / "settings.json"


def read_settings(data_root: Path) -> dict:
    path = settings_path(data_root)
    if not path.exists():
        return dict(DEFAULT_SETTINGS)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return dict(DEFAULT_SETTINGS)
    if not isinstance(payload, dict):
        return dict(DEFAULT_SETTINGS)
    settings = dict(DEFAULT_SETTINGS)
    for key in DEFAULT_SETTINGS:
        if key in payload and payload[key] is not None:
            settings[key] = str(payload[key]).strip()
    settings["schema_version"] = SETTINGS_SCHEMA_VERSION
    return settings


def write_settings(data_root: Path, settings: dict) -> dict:
    data_root.mkdir(parents=True, exist_ok=True)
    path = settings_path(data_root)
    with _locked_file(data_root / ".settings.lock"):
        current = read_settings(data_root)
        for key in DEFAULT_SETTINGS:
            if key in settings and settings[key] is not None:
                current[key] = str(settings[key]).strip()
        current["schema_version"] = SETTINGS_SCHEMA_VERSION
        _atomic_write_json(path, current)
        return current


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


class _locked_file:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None

    def __enter__(self) -> "_locked_file":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+", encoding="utf-8")
        try:
            import fcntl

            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        except ImportError:
            pass
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.handle is None:
            return
        try:
            import fcntl

            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        except ImportError:
            pass
        self.handle.close()
