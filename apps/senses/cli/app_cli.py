"""CLI entrypoint for Senses."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from service import app_events_for_action, handle_action, normalize_action


CLI_ACTIONS = {
    "manifest",
    "operations.manifest",
    "health",
    "health.check",
    "status",
    "reference_manifest",
    "references.manifest",
}


payload = read_entrypoint_payload()
arguments = dict(payload.arguments)
arguments["_workspace_id"] = payload.workspace_id
arguments["_app_id"] = payload.app_id
arguments["_app_dependencies"] = payload.raw.get("app_dependencies", {})
arguments["_app_actor"] = {
    "user_id": payload.user_id,
    "workspace_role": payload.workspace_role,
    "platform_role": payload.platform_role,
    "effective_mode": payload.effective_mode,
}
action = normalize_action(arguments.get("action"))
if action not in CLI_ACTIONS:
    emit_json(
        {
            "ok": False,
            "error": "unsupported_cli_action",
            "detail": f"Senses CLI action `{action}` is not available in Phase 4 CLI context.",
            "allowed_actions": sorted(CLI_ACTIONS),
            "status_code": 400,
        }
    )
    raise SystemExit(0)
arguments["action"] = action
status_code, result = handle_action(Path(payload.data_root), arguments)
result["status_code"] = status_code
if status_code < 400:
    result["app_events"] = app_events_for_action(action)
emit_json(result)
