"""App-store app service layer."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID
from typing import Any

from store import clear_custom_view, load_state, pinned_apps, remember_install, set_custom_view, set_pinned_apps, set_view_filter, toggle_pinned_app, view_filter_state

REFERENCE_MANIFEST = {
    "app_id": "app-store",
    "schema_version": "1",
    "entity_types": [
        {"entity_type": "installed_app", "display_name": "Installed App", "id_stability": "stable", "searchable": True, "resolvable": True, "summarizable": True, "deep_link_supported": True}
    ],
}

DATA_CHANGED_ACTIONS = {"pinned_apps.set", "pinned_apps.toggle", "remember_install"}
VIEW_STATE_ACTIONS = {"view_filter", "set_view_filter", "set_custom_view", "clear_custom_view"}
PUBLIC_STORE_METADATA_KEY = "public_store"
PUBLIC_APP_UUID_KEY = "public_app_uuid"
APP_EVENTS_RESULT_KEY = "_app_events"
STATE_CHANGED_EVENT = {"type": "maverick.app.data-changed", "resource": "state"}


class AppStoreValidationError(ValueError):
    """Raised when an app-store request payload is invalid."""


def app_events_for_action(action: str, result: dict[str, Any] | None = None) -> list[dict]:
    events: list[dict] = []
    if action in DATA_CHANGED_ACTIONS:
        events.append(STATE_CHANGED_EVENT)
    if action in VIEW_STATE_ACTIONS:
        events.append({"type": "maverick.app.data-changed", "resource": "view-state"})
    if isinstance(result, dict):
        result_events = result.get(APP_EVENTS_RESULT_KEY)
        if isinstance(result_events, list):
            events.extend(event for event in result_events if isinstance(event, dict))
    return events


def strip_internal_result_fields(result: dict[str, Any]) -> dict[str, Any]:
    result.pop(APP_EVENTS_RESULT_KEY, None)
    return result


def handle_action(
    data_root: Path,
    body: dict[str, Any],
    *,
    workspace_root: Path | None = None,
    launchable_app_ids: list[str] | None = None,
) -> tuple[int, dict[str, Any]]:
    action = str(body.get("action") or "catalog")
    if action == "state":
        return 200, {"state": load_state(data_root), "core_catalog_endpoint": "/api/app-store/apps"}
    if action == "catalog":
        raise AppStoreValidationError("Catalog data is served only by the core `/api/app-store/apps` API.")
    if action == "public_store.url":
        raise AppStoreValidationError("Public App Store access must use a core-owned API surface.")
    if action == "public_submissions.identity":
        source_root = _resolve_public_submission_source(body=body, workspace_root=workspace_root)
        contract = _read_contract(source_root / "app_contract.json")
        public_app_uuid = _public_app_uuid_from_contract(contract)
        return 200, {
            "identity": {
                "app_id": str(contract.get("app_id") or "").strip(),
                "name": str(contract.get("name") or "").strip(),
                "version": str(contract.get("version") or "").strip(),
                "public_app_uuid": public_app_uuid,
                "has_public_identity": bool(public_app_uuid),
            }
        }
    if action == "public_submissions.create":
        raise AppStoreValidationError("Public App Store submission must use a core-owned API surface.")
    if action == "public_submissions.read":
        raise AppStoreValidationError("Public App Store submission status must use a core-owned API surface.")
    if action == "view_filter":
        return 200, {"state": {"view_filter": view_filter_state(data_root)}}
    if action == "set_view_filter":
        try:
            state = set_view_filter(data_root, query=body.get("query"), scope=body.get("scope"), preserve_custom=bool(body.get("preserve_custom")))
        except ValueError as error:
            raise AppStoreValidationError(str(error)) from error
        return 200, {"state": state}
    if action == "set_custom_view":
        try:
            state = set_custom_view(data_root, title=body.get("title"), refs=body.get("refs"), query=body.get("query"), scope=body.get("scope"))
        except ValueError as error:
            raise AppStoreValidationError(str(error)) from error
        return 200, {"state": state}
    if action == "clear_custom_view":
        return 200, {"state": clear_custom_view(data_root)}
    if action == "pinned_apps.list":
        if launchable_app_ids is None:
            return 200, {"pinned_apps": pinned_apps(data_root)}
        repaired, changed = repair_pinned_apps(data_root, launchable_app_ids)
        result = {"pinned_apps": repaired}
        if changed:
            result[APP_EVENTS_RESULT_KEY] = [STATE_CHANGED_EVENT]
        return 200, result
    if action == "pinned_apps.set":
        if launchable_app_ids is None:
            raise AppStoreValidationError("Pinned app mutations require workspace app registry context.")
        raw_app_ids = body.get("app_ids")
        app_ids = [str(item).strip() for item in raw_app_ids] if isinstance(raw_app_ids, list) else []
        return 200, {"state": set_pinned_apps(data_root, _launchable_pinned_app_ids(app_ids, launchable_app_ids))}
    if action == "pinned_apps.toggle":
        if launchable_app_ids is None:
            raise AppStoreValidationError("Pinned app mutations require workspace app registry context.")
        app_id = str(body.get("app_id") or "").strip()
        if not app_id:
            raise AppStoreValidationError("app_id is required.")
        current = pinned_apps(data_root)
        if app_id not in current and app_id not in _launchable_app_id_set(launchable_app_ids):
            raise AppStoreValidationError(f"App `{app_id}` does not expose a launchable workspace frontend.")
        return 200, {"state": toggle_pinned_app(data_root, app_id)}
    if action == "remember_install":
        app_id = str(body.get("app_id") or "").strip()
        version = str(body.get("version") or "").strip()
        raw_workspace_ids = body.get("workspace_ids")
        workspace_ids = [str(item).strip() for item in raw_workspace_ids] if isinstance(raw_workspace_ids, list) else []
        if not app_id or not version or not workspace_ids:
            raise AppStoreValidationError("app_id, version, and workspace_ids are required.")
        return 200, {"state": remember_install(data_root, app_id=app_id, version=version, workspace_ids=workspace_ids)}
    if action == "references.manifest":
        return 200, REFERENCE_MANIFEST
    if action == "references.search":
        query = str(body.get("query") or "").casefold()
        state = load_state(data_root)
        installs = [item for item in state.get("recent_installs", []) if isinstance(item, dict)]
        results = [
            {
                "app_id": "app-store",
                "entity_type": "installed_app",
                "entity_id": str(item.get("app_id") or ""),
                "title": str(item.get("app_id") or ""),
                "subtitle": str(item.get("version") or ""),
                "summary": "Installed in " + ", ".join(str(workspace_id) for workspace_id in item.get("workspace_ids", [])),
                "confidence": 1.0,
                "deep_link": f"/apps/app-store/apps/{item.get('app_id')}",
            }
            for item in installs
            if str(item.get("app_id") or "")
        ]
        if query:
            results = [item for item in results if query in item["title"].casefold()]
        return 200, {"results": results[: max(1, min(int(body.get("limit") or 10), 50))]}
    if action == "references.resolve":
        entity_id = str(body.get("entity_id") or "").strip()
        status, payload = handle_action(data_root, {"action": "references.search", "query": entity_id, "limit": 50})
        item = next((candidate for candidate in payload.get("results", []) if candidate["entity_id"] == entity_id), None)
        return 200, {"exists": False, "app_id": "app-store", "entity_type": "installed_app", "entity_id": entity_id} if item is None else {"exists": True, **item}
    if action == "references.summarize":
        entity_id = str(body.get("entity_id") or "").strip()
        _status, payload = handle_action(data_root, {"action": "references.resolve", "entity_id": entity_id})
        return 200, {"summary": "", "safe_fields": {}, "source_updated_at": ""} if not payload.get("exists") else {
            "summary": payload.get("summary", ""),
            "safe_fields": {"app_id": payload.get("entity_id"), "version": payload.get("subtitle")},
            "source_updated_at": "",
        }
    raise AppStoreValidationError(f"Unknown action `{action}`.")


def _launchable_pinned_app_ids(app_ids: list[str], launchable_app_ids: list[str]) -> list[str]:
    launchable = _launchable_app_id_set(launchable_app_ids)
    return [app_id for app_id in app_ids if app_id in launchable]


def repair_pinned_apps(data_root: Path, launchable_app_ids: list[str]) -> tuple[list[str], bool]:
    current = pinned_apps(data_root)
    repaired = _launchable_pinned_app_ids(current, launchable_app_ids)
    if repaired != current:
        set_pinned_apps(data_root, repaired)
        return repaired, True
    return repaired, False


def _launchable_app_id_set(app_ids: list[str]) -> set[str]:
    return {str(app_id).strip() for app_id in app_ids if str(app_id).strip()}


def _resolve_public_submission_source(*, body: dict[str, Any], workspace_root: Path | None) -> Path:
    app_id = str(body.get("source_app_id") or body.get("app_id") or "").strip()
    if not app_id:
        raise AppStoreValidationError("source_app_id is required.")
    source_kind = str(body.get("source_kind") or "workspace_local").strip()
    if source_kind != "workspace_local":
        raise AppStoreValidationError("Only workspace-local public submissions are supported by this client flow.")
    if workspace_root is None:
        raise AppStoreValidationError("workspace_root is required to package workspace-local apps.")
    repo_root = workspace_root.parent.parent
    workspace_id = str(body.get("source_workspace_id") or workspace_root.name).strip()
    source_root = (repo_root / "workspaces" / workspace_id / "apps" / app_id).resolve(strict=False)
    allowed_root = (repo_root / "workspaces" / workspace_id / "apps").resolve(strict=False)
    if allowed_root != source_root and allowed_root not in source_root.parents:
        raise AppStoreValidationError("Resolved app source escapes the workspace apps directory.")
    if not (source_root / "app_contract.json").is_file():
        raise AppStoreValidationError(f"Workspace-local app `{app_id}` does not have an app_contract.json.")
    return source_root


def _read_contract(contract_path: Path) -> dict[str, Any]:
    payload = json.loads(contract_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AppStoreValidationError("app_contract.json must contain a JSON object.")
    return payload


def _public_app_uuid_from_contract(contract: dict[str, Any]) -> str:
    metadata = contract.get(PUBLIC_STORE_METADATA_KEY)
    if not isinstance(metadata, dict):
        return ""
    public_app_uuid = str(metadata.get(PUBLIC_APP_UUID_KEY) or "").strip()
    if not public_app_uuid:
        return ""
    try:
        return str(UUID(public_app_uuid))
    except ValueError as error:
        raise AppStoreValidationError("public_store.public_app_uuid must be a valid UUID.") from error
