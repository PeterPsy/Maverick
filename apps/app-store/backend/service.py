"""App-store app service layer."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from urllib.request import urlopen

from store import load_state, pinned_apps, remember_install, set_pinned_apps, toggle_pinned_app

REFERENCE_MANIFEST = {
    "app_id": "app-store",
    "schema_version": "1",
    "entity_types": [
        {"entity_type": "installed_app", "display_name": "Installed App", "id_stability": "stable", "searchable": True, "resolvable": True, "summarizable": True, "deep_link_supported": True}
    ],
}

DATA_CHANGED_ACTIONS = {"pinned_apps.set", "pinned_apps.toggle", "remember_install"}
DEFAULT_CATALOG_URL = "https://maverick-app-store.versy.ai"


class AppStoreValidationError(ValueError):
    """Raised when an app-store request payload is invalid."""


def app_events_for_action(action: str) -> list[dict]:
    if action not in DATA_CHANGED_ACTIONS:
        return []
    return [{"type": "maverick.app.data-changed", "resource": "state"}]


def catalog_url() -> str:
    return (os.environ.get("MAVERICK_APP_STORE_URL") or DEFAULT_CATALOG_URL).strip().rstrip("/")


def fetch_catalog() -> dict[str, Any]:
    base_url = catalog_url()
    url = urljoin(base_url.rstrip("/") + "/", "api/apps")
    with urlopen(url, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise AppStoreValidationError("Catalog response must be a JSON object.")
    return payload


def handle_action(data_root: Path, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    action = str(body.get("action") or "catalog")
    if action == "state":
        return 200, {"state": load_state(data_root), "catalog_url": catalog_url()}
    if action == "catalog":
        return 200, fetch_catalog()
    if action == "pinned_apps.list":
        return 200, {"pinned_apps": pinned_apps(data_root)}
    if action == "pinned_apps.set":
        raw_app_ids = body.get("app_ids")
        app_ids = [str(item).strip() for item in raw_app_ids] if isinstance(raw_app_ids, list) else []
        return 200, {"state": set_pinned_apps(data_root, app_ids)}
    if action == "pinned_apps.toggle":
        app_id = str(body.get("app_id") or "").strip()
        if not app_id:
            raise AppStoreValidationError("app_id is required.")
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
