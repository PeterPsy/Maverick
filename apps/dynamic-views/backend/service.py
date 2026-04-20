"""Dynamic Views app service layer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from errors import DynamicViewsValidationError
from store import chat_render, create_instance, load_state, normalize_instance, save_state, seed_state


def _owner_user_id(body: dict[str, Any], source_instance_id: str | None) -> str:
    owner = str(body.get("owner_user_id") or "").strip()
    if owner:
        return owner
    source = str(source_instance_id or body.get("source_instance_id") or "").strip()
    return source or "workspace"


def _target_id(body: dict[str, Any]) -> str:
    return str(body.get("id") or body.get("target_id") or body.get("instance_id") or "").strip()


def _hydrate_all(state: dict) -> list[dict]:
    items: list[dict] = []
    for instance in state["instances"]:
        package = next((item for item in state["packages"] if item.get("id") == instance.get("package_id")), None)
        if package is not None:
            items.append(normalize_instance(instance, package))
    return sorted(items, key=lambda item: item["updated_at"], reverse=True)


def _read_instance(data_root: Path, instance_id: str) -> dict:
    if not instance_id:
        raise DynamicViewsValidationError("Dynamic view id is required.")
    state = load_state(data_root)
    for item in _hydrate_all(state):
        if item["id"] == instance_id:
            return item
    raise DynamicViewsValidationError("Dynamic view instance not found.")


def _delete_instance(data_root: Path, instance_id: str) -> dict:
    if not instance_id:
        raise DynamicViewsValidationError("Dynamic view id is required.")
    state = load_state(data_root)
    before = len(state["instances"])
    state["instances"] = [item for item in state["instances"] if item.get("id") != instance_id]
    deleted = before - len(state["instances"])
    save_state(data_root, state)
    return {"action": "delete", "summary": f"dynamic view delete | id={instance_id} | deleted={deleted}", "status": "ok", "deleted": deleted}


def handle_action(
    data_root: Path,
    *,
    workspace_id: str,
    source_instance_id: str | None,
    body: dict[str, Any],
) -> tuple[int, dict[str, Any]]:
    action = str(body.get("action") or "list").strip().lower()
    if action in {"catalog", "list"}:
        items = _hydrate_all(load_state(data_root))
        limit = max(1, min(int(body.get("limit") or 50), 100))
        return 200, {"action": "list", "summary": f"dynamic views list | count={len(items[:limit])}", "items": items[:limit]}
    if action == "create":
        return 200, create_instance(
            data_root,
            workspace_id=workspace_id,
            owner_user_id=_owner_user_id(body, source_instance_id),
            source_instance_id=source_instance_id or str(body.get("source_instance_id") or "").strip() or None,
            payload=body,
        )
    if action in {"read", "recall"}:
        instance = _read_instance(data_root, _target_id(body))
        return 200, {
            "action": action,
            "summary": f"dynamic view {action} | id={instance['id']} | title={instance['title']}",
            "instance": instance,
            "chat_render": chat_render(instance),
        }
    if action == "delete":
        return 200, _delete_instance(data_root, _target_id(body))
    if action == "health.check":
        state = seed_state(data_root)
        return 200, {"status": "ok", "package_count": len(state["packages"]), "instance_count": len(state["instances"])}
    raise DynamicViewsValidationError(f"Unsupported dynamic view action: {action}")

