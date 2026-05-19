"""Workspace-owned Speech metadata and settings store."""

from __future__ import annotations

import json
from pathlib import Path

from models import (
    DEFAULT_TRANSCRIPTION_ENGINE,
)

MAX_JOBS = 100
SETTINGS_SCHEMA_VERSION = "1"
DEFAULT_SETTINGS = {
    "schema_version": SETTINGS_SCHEMA_VERSION,
    "synthesis_engine": "auto",
    "transcription_engine": DEFAULT_TRANSCRIPTION_ENGINE,
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
    payload = read_jobs(data_root)
    jobs = [job, *payload["jobs"]]
    payload["schema_version"] = "1"
    payload["jobs"] = jobs[:MAX_JOBS]
    jobs_path(data_root).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
    current = read_settings(data_root)
    for key in DEFAULT_SETTINGS:
        if key in settings and settings[key] is not None:
            current[key] = str(settings[key]).strip()
    current["schema_version"] = SETTINGS_SCHEMA_VERSION
    settings_path(data_root).write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return current
