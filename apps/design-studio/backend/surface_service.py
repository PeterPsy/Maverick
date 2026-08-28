"""Shared backend, CLI, MCP, reference, and view surfaces for Design Studio."""

from __future__ import annotations

import json
from pathlib import Path
import stat
from typing import Any

from delegation_errors import DelegationError
from delegation_service import DelegationService, public_delegation_error
from delegation_store import DelegationStore
from opendesign_client import OpenDesignClient, OpenDesignClientError, validated_identifier
from project_surfaces import ProjectSurfaces, sanitize_project


DELEGATION_ACTIONS = {
    "delegate",
    "delegation_status",
    "cancel_delegation",
    "delegation_result",
}
VIEW_ACTIONS = {"set_view_filter", "set_custom_view", "clear_custom_view"}


class SurfaceService:
    """Keep Maverick orchestration outside the native OpenDesign product."""

    def __init__(self, payload: Any, *, client: Any | None = None) -> None:
        self.payload = payload
        self.app_id = str(getattr(payload, "app_id", "") or "design-studio")
        self.store = DelegationStore(str(getattr(payload, "data_root", "") or ""))
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = OpenDesignClient(self.payload)
        return self._client

    def dispatch(self, action: str, arguments: dict[str, Any]) -> dict[str, Any]:
        canonical = str(action or "state")
        delegation = DelegationService(
            self.payload,
            client=self._client,
            store=self.store,
        )
        if canonical in {"state", "status"}:
            return self.state()
        try:
            if canonical == "delegate":
                return delegation.delegate(arguments)
            if canonical == "delegation_status":
                return delegation.status(_delegation_id(arguments))
            if canonical == "cancel_delegation":
                return delegation.cancel(_delegation_id(arguments))
            if canonical == "delegation_result":
                return delegation.result(_delegation_id(arguments))
        except Exception as error:
            raise public_delegation_error(error) from error
        if canonical == "view_filter":
            return {"state": {"view_filter": self.store.view_state()}}
        if canonical == "set_view_filter":
            return self.set_view_filter(arguments)
        if canonical == "set_custom_view":
            return self.set_custom_view(arguments)
        if canonical == "clear_custom_view":
            return self.clear_custom_view()
        try:
            projects = ProjectSurfaces(self.client, self.app_id)
            if canonical in {"references.manifest", "reference_manifest"}:
                return projects.reference_manifest()
            if canonical in {"references.search", "reference_search"}:
                return projects.reference_search(arguments)
            if canonical in {"references.resolve", "reference_resolve"}:
                return projects.reference_resolve(arguments)
            if canonical in {"references.summarize", "reference_summarize"}:
                return projects.reference_summarize(arguments)
        except Exception as error:
            raise public_delegation_error(error) from error
        raise DelegationError(
            "unsupported_action",
            f"Unsupported Design Studio action `{canonical}`.",
            status_code=400,
        )

    def state(self) -> dict[str, Any]:
        available = False
        project_count: int | None = None
        try:
            project_count = len(self.client.list_projects())
            available = True
        except (OpenDesignClientError, ValueError):
            pass
        data_root = Path(str(getattr(self.payload, "data_root", "") or ""))
        return {
            "mode": "official-native",
            "app_id": self.app_id,
            "native_data_owner": "opendesign",
            "intercepts_native_routes": False,
            "host": _host_status(data_root / "native-host-status.json"),
            "delegation_bridge": {
                "mode": "external-public-api-client",
                "available": available,
                "native_project_count": project_count,
                "stores_native_semantic_state": False,
            },
            "state": {
                "view_filter": self.store.view_state(),
                "delegations": self.store.records(limit=50),
            },
        }

    def set_view_filter(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = _bounded_string(arguments.get("query"), "query", 200)
        current = self.store.view_state()
        preserve = arguments.get("preserve_custom", False)
        if not isinstance(preserve, bool):
            raise DelegationError(
                "view_filter_invalid",
                "preserve_custom must be a boolean.",
                status_code=400,
            )
        view = {
            "mode": current["mode"] if preserve else "search",
            "query": query,
            "title": current["title"] if preserve else "",
            "project_ids": current["project_ids"] if preserve else [],
        }
        return {"state": {"view_filter": self.store.set_view_state(view)}}

    def set_custom_view(self, arguments: dict[str, Any]) -> dict[str, Any]:
        raw_ids = arguments.get("project_ids")
        if raw_ids is None:
            raw_ids = [arguments.get("project_id")] if arguments.get("project_id") else []
        if not isinstance(raw_ids, list) or not 1 <= len(raw_ids) <= 100:
            raise DelegationError(
                "custom_view_invalid",
                "Provide between 1 and 100 OpenDesign project ids.",
                status_code=400,
            )
        try:
            project_ids = [
                validated_identifier(value, label="OpenDesign project id")
                for value in raw_ids
            ]
            for project_id in project_ids:
                project = sanitize_project(self.client.get_project(project_id))
                if project["id"] != project_id:
                    raise ValueError("OpenDesign project identity mismatch.")
        except Exception as error:
            raise public_delegation_error(error) from error
        view = {
            "mode": "custom",
            "query": _bounded_string(arguments.get("query"), "query", 200),
            "title": _bounded_string(arguments.get("title"), "title", 120),
            "project_ids": list(dict.fromkeys(project_ids)),
        }
        return {"state": {"view_filter": self.store.set_view_state(view)}}

    def clear_custom_view(self) -> dict[str, Any]:
        return {
            "state": {
                "view_filter": self.store.set_view_state({
                    "mode": "search",
                    "query": "",
                    "title": "",
                    "project_ids": [],
                })
            }
        }


def app_events_for_action(action: str) -> list[dict[str, str]]:
    """Emit only declared bounded delegation/view invalidation events."""
    resource = "delegation" if action in DELEGATION_ACTIONS else "view-state" if action in VIEW_ACTIONS else ""
    return (
        [{
            "type": "maverick.app.data-changed",
            "owner_app_id": "design-studio",
            "resource": resource,
        }]
        if resource
        else []
    )


def _delegation_id(arguments: dict[str, Any]) -> str:
    value = arguments.get("delegation_id")
    if not isinstance(value, str):
        raise DelegationError(
            "delegation_id_invalid",
            "A valid delegation id is required.",
            status_code=400,
        )
    return value


def _bounded_string(value: object, label: str, maximum: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise DelegationError(f"{label}_invalid", f"{label} must be a string.", status_code=400)
    text = value.strip()
    if len(text) > maximum or "\x00" in text:
        raise DelegationError(
            f"{label}_invalid",
            f"{label} exceeds its bounded display limit.",
            status_code=400,
        )
    return text


def _host_status(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    model = payload.get("model_bridge") if isinstance(payload.get("model_bridge"), dict) else {}
    api = model.get("api") if isinstance(model.get("api"), dict) else {}
    cli = model.get("cli") if isinstance(model.get("cli"), dict) else {}
    return {
        "schema_version": payload.get("schema_version", ""),
        "mode": payload.get("mode", ""),
        "state": payload.get("state", ""),
        "version": payload.get("version", ""),
        "image": payload.get("image", ""),
        "manifest_digest": payload.get("manifest_digest", ""),
        "rootfs_snapshot_sha256": payload.get("rootfs_snapshot_sha256", ""),
        "customizations": payload.get("customizations", []),
        "model_bridge": {
            "state": model.get("state", ""),
            "semantic_enrichment": model.get("semantic_enrichment", False),
            "api": {"state": api.get("state", ""), "protocol": api.get("protocol", "")},
            "cli": {
                "state": cli.get("state", ""),
                "profile_id": cli.get("profile_id", ""),
                "model_count": cli.get("model_count", 0),
            },
        },
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
