"""Browser-owned user connector and agent operation surfaces."""

from __future__ import annotations

from pathlib import Path

import companion_connections as connections
import companion_operations as operations
from errors import BrowserValidationError


USER_ACTIONS = frozenset({"companion.connect", "companion.poll", "companion.progress", "companion.complete", "companion.disconnect"})
COMPANION_ACTIONS = USER_ACTIONS | {"companion.overview", "operation.get", "operation.cancel", "instagram.collect", "video.analyze", "media.completed"}
FIELDS = {
    "companion.connect": {"display_name"},
    "companion.overview": set(),
    "companion.disconnect": {"session_id"},
    "companion.poll": {"session_id", "connector_secret", "url", "title", "active_operation_id"},
    "companion.progress": {"session_id", "connector_secret", "operation_id", "lease_id", "phase"},
    "companion.complete": {"session_id", "connector_secret", "operation_id", "lease_id", "result"},
    "operation.get": {"operation_id"},
    "operation.cancel": {"operation_id"},
}


def handles(action: str, body: dict) -> bool:
    return action in COMPANION_ACTIONS or str(body.get("session_id") or "").startswith("chrome-")


def handle(
    data_root: Path, body: dict, *, workspace_id: str | None, user_id: str | None,
    surface: str | None, runtime_session_id: str | None, dependencies: dict | None = None,
) -> tuple[int, dict]:
    action = str(body.get("action") or "companion.overview")
    if not workspace_id or not user_id and action != "media.completed":
        return 403, {"error": "actor_required", "detail": "A workspace-authenticated user is required for Chrome sharing."}
    if action in USER_ACTIONS and (surface != "backend" or runtime_session_id):
        return 403, {"error": "user_connector_required", "detail": "Chrome sharing and completion belong to the authenticated Browser UI."}
    try:
        if action == "media.completed":
            if surface != "dependency_backend_request_callback":
                return 403, {"error": "trusted_media_callback_required"}
            from companion_media import callback
            return 200, callback(data_root, workspace_id, user_id, body)
        if action in FIELDS:
            extras = set(body) - FIELDS[action] - {"action"}
            if extras:
                raise BrowserValidationError("This field is unavailable for the connector action.", field=sorted(extras)[0])
        if action == "companion.connect":
            name = body.get("display_name", "Chrome")
            if not isinstance(name, str) or not 1 <= len(name) <= 100:
                raise BrowserValidationError("display_name must have 1–100 characters.", field="display_name")
            return 201, connections.connect(data_root, workspace_id, user_id, name)
        if action == "companion.overview":
            return 200, {
                **connections.overview(data_root, workspace_id, user_id),
                "operations": operations.recent(data_root, workspace_id, user_id),
                "workspace_id": workspace_id,
            }
        if action == "companion.poll":
            return 200, operations.poll(data_root, workspace_id, user_id, body)
        if action == "companion.progress":
            return 200, operations.progress(data_root, workspace_id, user_id, body)
        if action == "companion.complete":
            return 200, operations.complete(data_root, workspace_id, user_id, body, dependencies)
        if action == "companion.disconnect":
            return 200, connections.disconnect(data_root, workspace_id, user_id, str(body.get("session_id") or ""))
        if action == "operation.get":
            return 200, operations.get(data_root, workspace_id, user_id, str(body.get("operation_id") or ""))
        if action == "operation.cancel":
            return 200, operations.cancel(data_root, workspace_id, user_id, str(body.get("operation_id") or ""))
        return 202, operations.enqueue(data_root, workspace_id, user_id, body)
    except connections.CompanionError as error:
        return error.status, {"error": error.code, "detail": str(error)}
    except BrowserValidationError as error:
        return 400, {"error": "validation_error", "detail": str(error), "field": error.field}
    except (TypeError, ValueError):
        return 400, {"error": "invalid_connector_payload", "detail": "The connector payload is invalid."}
