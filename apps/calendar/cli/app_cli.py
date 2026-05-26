"""CLI entrypoint for the Calendar app."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from service import AGENT_DEFAULT_LIST_LIMIT, app_events_for_action, handle_action
from surface_contract import normalize_action


payload = read_entrypoint_payload()
local_app_id = payload.app_id or "calendar"
arguments = dict(payload.arguments)
command_id = str(payload.raw.get("command_id") or "")
command_name = command_id.rsplit(".", 1)[-1]
default_action_by_command = {
    "calendar": "operations.manifest",
    "calendar-reference": "references.manifest",
}
arguments.setdefault("action", default_action_by_command.get(command_name, "operations.manifest"))
arguments["action"] = normalize_action(arguments.get("action"))
if arguments["action"] == "list":
    arguments.setdefault("profile", "compact")
    arguments.setdefault("include_description", False)
    arguments.setdefault("limit", AGENT_DEFAULT_LIST_LIMIT)
status_code, result = handle_action(
    Path(payload.data_root),
    arguments,
    app_id=local_app_id,
    workspace_id=payload.workspace_id,
)
result.update(
    {
        "app_id": local_app_id,
        "workspace_id": payload.workspace_id,
        "command_id": command_id,
        "status_code": status_code,
    }
)
if status_code < 400 and not result.get("idempotent_replay"):
    result["app_events"] = app_events_for_action(str(arguments.get("action") or result.get("action") or "list"), app_id=local_app_id)
emit_json(result)
