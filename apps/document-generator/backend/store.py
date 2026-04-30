"""Workspace data store for generated document jobs."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import re
from typing import Any

from core.app_sdk.storage import read_json_state, write_json_state
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
        write_json_state(data_root, "state.json", payload)
    seed_templates(data_root)
    return load_state(data_root)


def load_state(data_root: Path) -> dict[str, Any]:
    path = state_path(data_root)
    if not path.exists():
        return seed_state(data_root)
    payload = read_json_state(data_root, "state.json")
    if not isinstance(payload, dict):
        raise DocumentValidationError("state.json must contain a JSON object.")
    payload.setdefault("schema_version", SCHEMA_VERSION)
    payload.setdefault("view_filter", default_view_filter())
    return payload


def save_state(data_root: Path, state: dict[str, Any]) -> dict[str, Any]:
    data_root.mkdir(parents=True, exist_ok=True)
    state["schema_version"] = SCHEMA_VERSION
    write_json_state(data_root, "state.json", state)
    return state


def default_view_filter() -> dict[str, Any]:
    return {
        "mode": "search",
        "query": "",
        "format": "all",
        "title": "",
        "refs": [],
        "updated_at": utc_now(),
    }


def normalize_view_filter(raw_filter: object) -> dict[str, Any]:
    if not isinstance(raw_filter, dict):
        raw_filter = {}
    output_format = str(raw_filter.get("format") or "all").strip().lower() or "all"
    if output_format not in {"all", "docx", "pptx", "pdf", "xlsx"}:
        output_format = "all"
    refs = []
    for item in raw_filter.get("refs") if isinstance(raw_filter.get("refs"), list) else []:
        if not isinstance(item, dict):
            continue
        entity_id = str(item.get("entity_id") or "").strip()
        if str(item.get("entity_type") or "") == "document" and entity_id:
            refs.append({"entity_type": "document", "entity_id": entity_id})
    return {
        "mode": "custom" if str(raw_filter.get("mode") or "") == "custom" else "search",
        "query": str(raw_filter.get("query") or "").strip(),
        "format": output_format,
        "title": str(raw_filter.get("title") or "").strip(),
        "refs": refs,
        "updated_at": str(raw_filter.get("updated_at") or utc_now()),
    }


def view_state(data_root: Path) -> dict[str, Any]:
    state = load_state(data_root)
    state["view_filter"] = normalize_view_filter(state.get("view_filter"))
    save_state(data_root, state)
    return {"view_filter": state["view_filter"]}


def set_view_filter_payload(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    state = load_state(data_root)
    current = normalize_view_filter(state.get("view_filter"))
    preserve_custom = bool(body.get("preserve_custom")) and current.get("mode") == "custom"
    state["view_filter"] = normalize_view_filter(
        {
            "mode": "custom" if preserve_custom else "search",
            "query": body.get("query") if "query" in body else current.get("query"),
            "format": body.get("format") if "format" in body else current.get("format"),
            "title": current.get("title") if preserve_custom else "",
            "refs": current.get("refs") if preserve_custom else [],
            "updated_at": utc_now(),
        }
    )
    save_state(data_root, state)
    return {"view_filter": state["view_filter"]}


def set_custom_view_payload(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    state = load_state(data_root)
    state["view_filter"] = normalize_view_filter(
        {
            "mode": "custom",
            "query": body.get("query"),
            "format": body.get("format"),
            "title": body.get("title"),
            "refs": body.get("refs") if isinstance(body.get("refs"), list) else [],
            "updated_at": utc_now(),
        }
    )
    save_state(data_root, state)
    return {"view_filter": state["view_filter"]}


def clear_custom_view_payload(data_root: Path) -> dict[str, Any]:
    state = load_state(data_root)
    current = normalize_view_filter(state.get("view_filter"))
    state["view_filter"] = normalize_view_filter(
        {
            "mode": "search",
            "query": current.get("query"),
            "format": current.get("format"),
            "title": "",
            "refs": [],
            "updated_at": utc_now(),
        }
    )
    save_state(data_root, state)
    return {"view_filter": state["view_filter"]}


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
