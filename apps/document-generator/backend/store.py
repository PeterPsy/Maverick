"""Workspace data store for generated document jobs."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import re
from typing import Any

from errors import DocumentValidationError


SCHEMA_VERSION = "1"
SAFE_NAME_PATTERN = re.compile(r"[^a-zA-Z0-9._-]+")


def utc_now() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def state_path(data_root: Path) -> Path:
    return data_root / "state.json"


def jobs_root(data_root: Path) -> Path:
    return data_root / "jobs"


def templates_root(data_root: Path) -> Path:
    return data_root / "templates"


def seed_state(data_root: Path) -> dict[str, Any]:
    data_root.mkdir(parents=True, exist_ok=True)
    jobs_root(data_root).mkdir(parents=True, exist_ok=True)
    templates_root(data_root).mkdir(parents=True, exist_ok=True)
    path = state_path(data_root)
    if not path.exists():
        payload = {"schema_version": SCHEMA_VERSION, "created_at": utc_now(), "updated_at": utc_now()}
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    seed_templates(data_root)
    return load_state(data_root)


def load_state(data_root: Path) -> dict[str, Any]:
    path = state_path(data_root)
    if not path.exists():
        return seed_state(data_root)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise DocumentValidationError("state.json must contain a JSON object.")
    payload.setdefault("schema_version", SCHEMA_VERSION)
    return payload


def seed_templates(data_root: Path) -> None:
    root = templates_root(data_root)
    templates = {
        "docx-basic.json": {"format": "docx", "title": "Document", "sections": [{"heading": "Summary", "text": "Draft content."}]},
        "pptx-basic.json": {"format": "pptx", "title": "Presentation", "slides": [{"title": "Summary", "bullets": ["Draft content"]}]},
        "pdf-basic.json": {"format": "pdf", "title": "PDF Document", "sections": [{"heading": "Summary", "text": "Draft content."}]},
        "xlsx-basic.json": {"format": "xlsx", "title": "Workbook", "sheets": [{"name": "Sheet1", "rows": [["Metric", "Value"], ["Draft", 1]]}]},
    }
    for name, payload in templates.items():
        path = root / name
        if not path.exists():
            path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def list_templates(data_root: Path) -> list[dict[str, Any]]:
    seed_state(data_root)
    records: list[dict[str, Any]] = []
    for path in sorted(templates_root(data_root).glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        records.append({"template_id": path.stem, "path": path.name, "format": payload.get("format"), "title": payload.get("title")})
    return records


def safe_output_filename(raw_name: str | None, *, title: str, output_format: str) -> str:
    if raw_name and ("/" in raw_name or "\\" in raw_name or "\x00" in raw_name or ".." in Path(raw_name).parts):
        raise DocumentValidationError("output_filename must be a plain file name.")
    base = raw_name or title
    value = SAFE_NAME_PATTERN.sub("-", base.strip()).strip(".-_").lower()
    if not value:
        value = "document"
    suffix = f".{output_format}"
    if value.endswith(suffix):
        return value
    if "." in Path(value).name:
        value = Path(value).stem
    return f"{value}{suffix}"


def resolve_generated_path(generated_root: Path, filename: str) -> Path:
    relative = Path(filename)
    if relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 1:
        raise DocumentValidationError("output_filename must be a plain file name.")
    root = generated_root.resolve()
    target = (root / relative.name).resolve()
    if root != target.parent:
        raise DocumentValidationError("output path escapes generated storage.")
    return target


def save_job(data_root: Path, record: dict[str, Any]) -> dict[str, Any]:
    seed_state(data_root)
    job_id = str(record["job_id"])
    path = jobs_root(data_root) / f"{job_id}.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record


def list_jobs(data_root: Path) -> list[dict[str, Any]]:
    seed_state(data_root)
    records = []
    for path in sorted(jobs_root(data_root).glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            records.append(payload)
    return sorted(records, key=lambda item: str(item.get("created_at", "")), reverse=True)
