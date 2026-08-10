"""MCP entrypoint for `video-studio`."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from project_actions import actor_from_entrypoint, app_events_for_result, handle_action


TOOL_ACTIONS = {
    "video_studio_project_create": "project.create",
    "video_studio_project_list": "project.list",
    "video_studio_project_get": "project.get",
    "video_studio_project_rename": "project.rename",
    "video_studio_project_duplicate": "project.duplicate",
    "video_studio_project_archive": "project.archive",
    "video_studio_project_restore": "project.restore",
    "video_studio_revision_get": "revision.get",
    "video_studio_revision_compare": "revision.compare",
    "video_studio_native_export": "native.export",
    "video_studio_native_import": "native.import",
    "video_studio_operations_apply": "operations.apply",
    "video_studio_undo": "history.undo",
    "video_studio_redo": "history.redo",
}


def main() -> None:
    payload = read_entrypoint_payload()
    tool_name = str(payload.raw.get("tool_name") or "")
    if tool_name == "video_studio_reference_manifest":
        action = ""
        status_code, result = 200, {"ok": True, "entity_types": []}
    elif tool_name == "video_studio_foundation":
        action = str(payload.arguments.get("action") or "status").strip().lower()
        status_code, result = handle_action(
            payload.data_root,
            payload.workspace_id,
            payload.arguments,
            trusted_actor=actor_from_entrypoint(payload.raw),
        )
    elif tool_name in TOOL_ACTIONS:
        action = TOOL_ACTIONS[tool_name]
        request = {"action": action, **payload.arguments}
        status_code, result = handle_action(
            payload.data_root,
            payload.workspace_id,
            request,
            trusted_actor=actor_from_entrypoint(payload.raw),
        )
    else:
        action = ""
        status_code, result = 400, {
            "ok": False,
            "error": {"code": "unsupported_tool", "message": "Unsupported Video Studio tool."},
        }
    result.update({
        "app_id": "video-studio",
        "workspace_id": payload.workspace_id,
        "tool_name": tool_name,
        "status_code": status_code,
        "surface": "mcp",
    })
    if status_code < 400:
        result["app_events"] = app_events_for_result(action, result)
    emit_json(result)


if __name__ == "__main__":
    main()
