"""Workspace-owned Speech metadata store."""

from __future__ import annotations

import json
from pathlib import Path

MAX_JOBS = 100


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
