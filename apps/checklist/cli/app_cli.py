"""CLI entrypoint for the Checklist workspace app."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from service import app_events_for_action, handle_action


payload = read_entrypoint_payload()
arguments = dict(payload.arguments)
command_id = str(payload.raw.get("command_id") or "")
command_name = command_id.rsplit(".", 1)[-1]
default_action_by_command = {
    "checklist": "list",
    "checklist-reference": "references.manifest",
    "checklist-view": "view_filter",
}
arguments.setdefault("action", default_action_by_command.get(command_name, "list"))
status_code, result = handle_action(Path(payload.data_root), arguments, workspace_id=payload.workspace_id)
result.update(
    {
        "app_id": "checklist",
        "workspace_id": payload.workspace_id,
        "command_id": command_id,
        "status_code": status_code,
    }
)
if status_code < 400:
    result["app_events"] = app_events_for_action(str(arguments.get("action") or result.get("action") or "list"))
emit_json(result)
