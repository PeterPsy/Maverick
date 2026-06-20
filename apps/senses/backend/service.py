"""Phase 0 service layer for Senses."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from database import SCHEMA_VERSION, health_payload, require_workspace_id


APP_ID = "senses"
PHASE = "phase-0"
REQUIRED_DEPENDENCIES = (
    {
        "alias": "storage-file-content-write",
        "interface": "file.content.write",
        "version": "^1",
        "required": True,
    },
    {
        "alias": "storage-file-catalog",
        "interface": "file.catalog",
        "version": "^1",
        "required": True,
    },
)
DECLARED_BACKEND_ACTIONS = ("manifest", "health")
DEFERRED_ACTIONS = (
    "pairing.start",
    "pairing.complete",
    "ingest.frame",
    "routing.dispatch_capture",
    "device-token ingress",
)


def handle_action(data_root: Path, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
    action = normalize_action(payload.get("action"))
    workspace_id = workspace_id_from_payload(payload)
    if workspace_id is None:
        return 400, {
            "error": "missing_workspace_id",
            "detail": "Senses requires a workspace_id from the Maverick host payload.",
        }
    dependencies = dependency_resolution_payload(payload.get("_app_dependencies") or payload.get("app_dependencies"))
    if action in {"manifest", "operations.manifest"}:
        return 200, manifest_payload(workspace_id=workspace_id, dependencies=dependencies)
    if action in {"health", "health.check", "status"}:
        return 200, {
            "ok": dependencies["status"] == "resolved",
            "app_id": APP_ID,
            "phase": PHASE,
            "status": "ready" if dependencies["status"] == "resolved" else "dependency_resolution_pending",
            "workspace_id": workspace_id,
            "storage": health_payload(data_root, workspace_id),
            "dependencies": dependencies,
        }
    if action in {"reference_manifest", "references.manifest"}:
        return 200, reference_manifest()
    return 400, {
        "error": "unsupported_action",
        "detail": f"Unsupported Senses Phase 0 action `{action}`.",
        "allowed_actions": list(DECLARED_BACKEND_ACTIONS),
        "deferred_actions": list(DEFERRED_ACTIONS),
    }


def normalize_action(value: object) -> str:
    return str(value or "manifest").strip() or "manifest"


def workspace_id_from_payload(payload: dict[str, object]) -> str | None:
    value = payload.get("_workspace_id") or payload.get("workspace_id")
    try:
        return require_workspace_id(str(value) if value is not None else None)
    except ValueError:
        return None


def manifest_payload(*, workspace_id: str, dependencies: dict[str, object]) -> dict[str, object]:
    return {
        "app_id": APP_ID,
        "name": "Senses",
        "version": "0.1.0",
        "phase": PHASE,
        "workspace_id": workspace_id,
        "schema_version": SCHEMA_VERSION,
        "declared_surfaces": {
            "backend": True,
            "cli": ["senses"],
            "mcp": ["senses_operations_manifest", "senses_reference_manifest"],
            "frontend": False,
            "reference_entities": [],
            "skills": [],
        },
        "backend_actions": list(DECLARED_BACKEND_ACTIONS),
        "required_dependencies": list(REQUIRED_DEPENDENCIES),
        "dependency_resolution": dependencies,
        "deferred_to_later_phases": list(DEFERRED_ACTIONS),
        "notes": [
            "Senses Phase 0 exposes availability and dependency health only.",
            "Frame ingestion, pairing, device-token ingress, and routing are intentionally not implemented.",
        ],
    }


def reference_manifest() -> dict[str, object]:
    return {
        "app_id": APP_ID,
        "schema_version": "1",
        "entity_types": [],
        "notes": ["Senses reference entities are deferred until device and capture records exist."],
    }


def dependency_resolution_payload(raw_dependencies: object) -> dict[str, object]:
    if not isinstance(raw_dependencies, dict) or not isinstance(raw_dependencies.get("dependencies"), list):
        return {
            "status": "unknown",
            "blocked_reason": "dependency_resolution_not_provided_by_host",
            "dependencies": [
                {**dependency, "status": "unknown", "selected_provider_app_ids": []}
                for dependency in REQUIRED_DEPENDENCIES
            ],
        }
    dependencies_by_alias = {
        str(item.get("alias")): item
        for item in raw_dependencies.get("dependencies", [])
        if isinstance(item, dict)
    }
    required = []
    for dependency in REQUIRED_DEPENDENCIES:
        resolved = dependencies_by_alias.get(str(dependency["alias"]))
        if isinstance(resolved, dict):
            required.append(_compact_dependency(resolved))
        else:
            required.append({**dependency, "status": "missing_declaration", "selected_provider_app_ids": []})
    blocked = [item for item in required if str(item.get("status")) not in {"resolved"}]
    return {
        "status": "blocked" if blocked else "resolved",
        "workspace_id": raw_dependencies.get("workspace_id"),
        "consumer_app_id": raw_dependencies.get("consumer_app_id"),
        "dependencies": required,
        "blocked_reason": "; ".join(
            str(item.get("blocked_reason") or item.get("status") or "")
            for item in blocked
            if str(item.get("blocked_reason") or item.get("status") or "").strip()
        ) or None,
    }


def _compact_dependency(item: dict[str, Any]) -> dict[str, object]:
    return {
        "alias": item.get("alias"),
        "interface": item.get("interface"),
        "version": item.get("version"),
        "required": item.get("required"),
        "cardinality": item.get("cardinality"),
        "status": item.get("status"),
        "selected_provider_app_ids": item.get("selected_provider_app_ids") or [],
        "candidate_provider_app_ids": [
            candidate.get("app_id")
            for candidate in item.get("candidates", [])
            if isinstance(candidate, dict) and candidate.get("app_id")
        ],
        "blocked_reason": item.get("blocked_reason"),
    }


def app_events_for_action(action: str) -> list[dict[str, str]]:
    return []
