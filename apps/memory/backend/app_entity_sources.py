"""App-entity source snapshots for Memory ingestion."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

from app_surface_transport import run_maverick_app_mcp
from content_store import body_hash, canonical_body
from errors import MemoryValidationError


def fetch_app_entity_source(data_root: Path, request: dict[str, str]) -> dict[str, Any]:
    """Fetch a redaction-safe app entity summary through official app reference surfaces."""

    owning_app_id = request["owning_app_id"]
    entity_type = request["entity_type"]
    entity_id = request["entity_id"]
    if not shutil.which("maverick"):
        raise MemoryValidationError("app_entity ingest requires the Maverick app reference surface.")
    workspace_root = workspace_root_for_data_root(data_root)
    if workspace_root is None:
        raise MemoryValidationError("Memory data_root must live under a workspace data directory for app_entity ingestion.")
    tools = discover_reference_tools(workspace_root, owning_app_id)
    validate_reference_manifest(workspace_root, owning_app_id, tools.get("manifest", ""), entity_type)
    summary_response: dict[str, Any] | None = None
    for action in ("summarize", "resolve"):
        tool_name = tools.get(action, "")
        if not tool_name:
            continue
        completed = run_reference_tool(
            workspace_root,
            owning_app_id=owning_app_id,
            tool_name=tool_name,
            entity_type=entity_type,
            entity_id=entity_id,
        )
        response = _reference_response(completed)
        if response is None:
            continue
        if action == "summarize" and not reference_snapshot_has_locator(response):
            summary_response = response
            continue
        if summary_response is not None:
            return merge_reference_snapshots(response, summary_response)
        if response is not None:
            return response
    if summary_response is not None:
        return summary_response
    raise MemoryValidationError("app_entity reference surface could not summarize or resolve the entity.")


def app_entity_body(snapshot: dict[str, Any], *, fallback_title: str, fallback_summary: str) -> str:
    title = str(snapshot.get("title") or snapshot.get("label") or fallback_title).strip()
    subtitle = str(snapshot.get("subtitle") or "").strip()
    summary = str(snapshot.get("summary") or fallback_summary).strip()
    deep_link = str(snapshot.get("deep_link") or snapshot.get("app_page") or "").strip()
    lines = [line for line in (title, subtitle, summary) if line]
    if deep_link:
        lines.append(f"Reference: {deep_link}")
    return canonical_body("\n\n".join(lines))


def app_entity_version_hash(
    *,
    owning_app_id: str,
    entity_type: str,
    entity_id: str,
    body_markdown: str,
    snapshot: dict[str, Any],
) -> str:
    payload = {
        "owning_app_id": owning_app_id,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "body_sha256": body_hash(body_markdown),
        "title": snapshot.get("title") or snapshot.get("label") or "",
        "summary": snapshot.get("summary") or "",
        "deep_link": snapshot.get("deep_link") or snapshot.get("app_page") or "",
    }
    return sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def workspace_root_for_data_root(data_root: Path) -> Path | None:
    if data_root.parent.name != "data":
        return None
    return data_root.parent.parent


def reference_snapshot_has_locator(snapshot: dict[str, Any]) -> bool:
    return bool(
        str(snapshot.get("deep_link") or snapshot.get("app_page") or "").strip()
        and str(snapshot.get("title") or snapshot.get("label") or "").strip()
    )


def merge_reference_snapshots(resolved: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    merged = dict(resolved)
    for key, value in summary.items():
        if value in ("", None, [], {}):
            continue
        if key == "safe_fields" and isinstance(value, dict) and isinstance(merged.get("safe_fields"), dict):
            merged["safe_fields"] = {**merged["safe_fields"], **value}
            continue
        merged[key] = value
    return merged


def discover_reference_tools(workspace_root: Path, owning_app_id: str) -> dict[str, str]:
    completed = run_maverick_app_mcp(workspace_root, app_id=owning_app_id, operation="list")
    if completed.returncode != 0:
        raise MemoryValidationError("app_entity ingest could not discover the app reference surface.")
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as error:
        raise MemoryValidationError("app_entity reference discovery returned invalid JSON.") from error
    declared_tools = payload.get("tools") if isinstance(payload.get("tools"), list) else []
    names = [str(tool.get("name") or "").strip() for tool in declared_tools if isinstance(tool, dict)]
    discovered: dict[str, str] = {}
    for action in ("manifest", "search", "resolve", "summarize"):
        discovered[action] = preferred_reference_tool_name(names, owning_app_id=owning_app_id, action=action)
    if not discovered.get("summarize") and not discovered.get("resolve"):
        raise MemoryValidationError("app_entity ingest requires declared reference summarize or resolve tools.")
    return discovered


def preferred_reference_tool_name(names: list[str], *, owning_app_id: str, action: str) -> str:
    suffix = f"_reference_{action}"
    candidates = sorted(name for name in names if name.endswith(suffix))
    if not candidates:
        return ""
    preferred_prefix = owning_app_id.replace("-", "_")
    for name in candidates:
        if name.startswith(f"{preferred_prefix}_"):
            return name
    return candidates[0]


def validate_reference_manifest(workspace_root: Path, owning_app_id: str, tool_name: str, entity_type: str) -> None:
    if not tool_name:
        return
    completed = run_maverick_app_mcp(workspace_root, app_id=owning_app_id, operation="call", tool_name=tool_name)
    response = _reference_response(completed)
    if response is None:
        return
    entity_types = response.get("entity_types") if isinstance(response.get("entity_types"), list) else []
    supported = {str(item.get("entity_type") or "").strip() for item in entity_types if isinstance(item, dict)}
    if supported and entity_type not in supported:
        raise MemoryValidationError("app_entity reference surface does not support the requested entity_type.")


def run_reference_tool(
    workspace_root: Path,
    *,
    owning_app_id: str,
    tool_name: str,
    entity_type: str,
    entity_id: str,
) -> subprocess.CompletedProcess[str]:
    return run_maverick_app_mcp(
        workspace_root,
        app_id=owning_app_id,
        operation="call",
        tool_name=tool_name,
        arguments={"entity_type": entity_type, "entity_id": entity_id},
    )


def _reference_response(completed: subprocess.CompletedProcess[str]) -> dict[str, Any] | None:
    try:
        response = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as error:
        raise MemoryValidationError("app_entity reference surface returned invalid JSON.") from error
    if completed.returncode != 0:
        return None
    status_code = int(response.get("status_code") or 200)
    if status_code >= 400:
        return None
    if response.get("exists") is False:
        raise MemoryValidationError("app_entity reference does not exist.")
    return response
