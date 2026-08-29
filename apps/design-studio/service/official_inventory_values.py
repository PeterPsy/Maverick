"""Stable, redaction-safe values derived from official public API responses."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote

from official_inventory_process import OfficialApiClient
from official_opendesign_release import OfficialReleaseError


def design_system_files(client: OfficialApiClient, system_id: str) -> list[dict[str, Any]]:
    payload = client.get_json(f"/api/design-systems/{quote(system_id, safe='')}/files")
    files = object_list(payload, "files")
    records: list[dict[str, Any]] = []
    for item in sorted(files, key=lambda value: str(value.get("path") or "")):
        path = safe_file_path(item.get("path"))
        record = {
            key: stable_value(item.get(key))
            for key in ("path", "name", "kind", "size")
            if key in item
        }
        if item.get("kind") != "folder":
            detail = client.get_json(
                "/api/design-systems/"
                f"{quote(system_id, safe='')}/file?path={quote(path, safe='')}"
            )
            file_payload = detail.get("file")
            if not isinstance(file_payload, dict) or file_payload.get("path") != path:
                raise OfficialReleaseError("official design system file identity mismatch")
            content = file_payload.get("content")
            if not isinstance(content, str):
                raise OfficialReleaseError("official design system file content is invalid")
            record["content_sha256"] = sha256(content.encode("utf-8")).hexdigest()
        records.append(record)
    return records


def category_digest(records: list[Any]) -> dict[str, Any]:
    return {"count": len(records), "sha256": canonical_digest(records)}


def stable_project(project: dict[str, Any]) -> dict[str, Any]:
    """Retain every public project field except explicit server volatility.

    The upstream public schema can grow between releases.  A positive field
    list would silently discard those new values before the migration guard
    sees them, so normalization is intentionally denylist-based.
    """
    return _stable_project(project, excluded=PROJECT_VOLATILE_FIELDS)


def stable_project_list(project: dict[str, Any]) -> dict[str, Any]:
    """Retain the distinct list representation minus explicit server run state."""
    return _stable_project(project, excluded=PROJECT_LIST_SERVER_FIELDS)


def _stable_project(
    project: dict[str, Any],
    *,
    excluded: set[str],
) -> dict[str, Any]:
    return {
        str(key): stable_value(value)
        for key, value in sorted(project.items())
        if key not in excluded
    }


def stable_file(file_record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: stable_value(value)
        for key, value in file_record.items()
        if key not in {"mtime", "path", "name", "artifactManifest"}
    }


def stable_run(run: dict[str, Any]) -> dict[str, Any]:
    return {
        key: run.get(key)
        for key in ("id", "status", "projectId", "conversationId", "assistantMessageId")
        if key in run
    }


def stable_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): stable_value(item)
            for key, item in sorted(value.items())
            if key not in {"resolvedDir", "eventsLogPath", "pid"}
        }
    if isinstance(value, list):
        return [stable_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise OfficialReleaseError("official API inventory contained an unsupported value")


PROJECT_VOLATILE_FIELDS = {
    "createdAt",
    "updatedAt",
    "startedAt",
    "endedAt",
    "mtime",
    "pid",
    "resolvedDir",
    "eventsLogPath",
}
PROJECT_LIST_SERVER_FIELDS = {*PROJECT_VOLATILE_FIELDS, "status"}


def object_list(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise OfficialReleaseError(f"official API returned an invalid {key} list")
    return value


def identifier(value: object, label: str) -> str:
    result = str(value or "")
    if not result or len(result) > 128 or "/" in result or ".." in result:
        raise OfficialReleaseError(f"official API returned an invalid {label} id")
    return result


def safe_file_path(value: object) -> str:
    path = str(value or "")
    pure = PurePosixPath(path)
    if not path or pure.is_absolute() or ".." in pure.parts or "\\" in path:
        raise OfficialReleaseError("official API returned an invalid project file path")
    return path


def created_order(item: dict[str, Any]) -> tuple[str, str]:
    return (str(item.get("createdAt") or ""), str(item.get("id") or ""))


def canonical_digest(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return sha256(body).hexdigest()
