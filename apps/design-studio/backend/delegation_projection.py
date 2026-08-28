"""Display-safe projections of native OpenDesign delegation responses."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from opendesign_client import validated_identifier


TERMINAL_STATUSES = {"succeeded", "failed", "canceled"}


def normalized_run_status(value: object) -> str:
    """Map native progress states onto the bounded delegation status vocabulary."""
    status = str(value or "").strip().lower()
    if status in {"queued", "pending", "starting"}:
        return "queued"
    if status in {"running", "requesting", "thinking", "streaming"}:
        return "running"
    if status in {"awaiting_input", "needs_input"}:
        return "awaiting_input"
    if status in {"succeeded", "completed", "done", "success"}:
        return "succeeded"
    if status in {"failed", "error"}:
        return "failed"
    if status in {"canceled", "cancelled"}:
        return "canceled"
    return "unknown"


def assistant_run_projection(
    messages: list[dict[str, Any]],
    assistant_message_id: str,
) -> dict[str, str]:
    """Recover only canonical run correlation/status/cursor from one native message."""
    for message in messages:
        if str(message.get("id") or "") != assistant_message_id:
            continue
        run_id = _identifier_or_empty(message.get("runId"), "OpenDesign run id")
        cursor = _event_cursor(message.get("lastRunEventId"))
        return {
            "run_id": run_id,
            "status": normalized_run_status(message.get("runStatus")),
            "event_cursor": cursor,
        }
    return {"run_id": "", "status": "unknown", "event_cursor": ""}


def sanitized_result_references(
    package: dict[str, Any],
    *,
    project_id: str,
    run_id: str,
) -> dict[str, Any]:
    """Omit manifests, paths, transcripts, process details, and body content."""
    run = package.get("run") if isinstance(package.get("run"), dict) else {}
    package_run_id = _identifier_or_empty(run.get("id"), "OpenDesign run id")
    if package_run_id and package_run_id != run_id:
        raise ValueError("OpenDesign result run identity mismatch.")
    project = package.get("project") if isinstance(package.get("project"), dict) else {}
    package_project_id = _identifier_or_empty(
        project.get("id"),
        "OpenDesign project id",
    )
    if package_project_id and package_project_id != project_id:
        raise ValueError("OpenDesign result project identity mismatch.")
    file_count = project.get("fileCount")
    safe_project = {
        "id": project_id,
        "name": _scalar(project.get("name"), 200),
        "file_count": file_count if isinstance(file_count, int) and not isinstance(file_count, bool) and file_count >= 0 else 0,
    }
    artifacts = package.get("artifacts") if isinstance(package.get("artifacts"), list) else []
    safe_artifacts: list[dict[str, str]] = []
    for index, artifact in enumerate(artifacts[:100]):
        if not isinstance(artifact, dict):
            continue
        safe_artifacts.append({
            "reference_id": f"artifact-{index + 1}",
            "title": _scalar(artifact.get("title"), 200),
            "kind": _scalar(artifact.get("kind"), 80),
            "renderer": _scalar(artifact.get("renderer"), 80),
            "status": _scalar(artifact.get("status"), 80),
        })
    return {
        "run_id": run_id,
        "project": safe_project,
        "artifacts": safe_artifacts,
    }


def uploaded_file_path(file_record: dict[str, Any], expected_path: str) -> str:
    """Accept only one safe project-relative path from an upload response."""
    value = file_record.get("path") or file_record.get("name") or expected_path
    path = str(value or "").strip()
    pure = PurePosixPath(path)
    if (
        not path
        or len(path) > 512
        or pure.is_absolute()
        or ".." in pure.parts
        or "\\" in path
        or any(not part or part == "." for part in pure.parts)
    ):
        raise ValueError("OpenDesign returned an invalid attachment path.")
    return path


def _identifier_or_empty(value: object, label: str) -> str:
    if value is None or not str(value).strip():
        return ""
    return validated_identifier(value, label=label)


def _event_cursor(value: object) -> str:
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, int) and value >= 0:
        return str(value)
    text = str(value).strip()
    return text if text.isdigit() and len(text) <= 32 else ""


def _scalar(value: object, maximum: int) -> str:
    return str(value or "").strip().replace("\x00", "")[:maximum]
