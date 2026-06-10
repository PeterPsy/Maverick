"""CLI entrypoint for the Browser app."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from errors import BrowserValidationError
from service import acceptance_smoke_payload, dev_smoke_payload, handle_action


payload = read_entrypoint_payload()
local_app_id = payload.app_id or "browser"
command_id = str(payload.raw.get("command_id") or "")
arguments = dict(payload.arguments)
arguments.setdefault("action", "operations.manifest")
if arguments.get("action") == "acceptance.smoke":
    try:
        status_code, result = acceptance_smoke_payload(
            Path(payload.data_root),
            arguments,
            app_id=local_app_id,
            workspace_id=payload.workspace_id,
            effective_mode=payload.effective_mode,
            platform_role=payload.platform_role,
            workspace_role=payload.workspace_role,
        )
    except BrowserValidationError as error:
        status_code = 400
        result = {"error": "validation_error", "detail": str(error), "field": error.field}
elif arguments.get("action") == "dev.smoke":
    try:
        status_code, result = dev_smoke_payload(
            Path(payload.data_root),
            arguments,
            app_id=local_app_id,
            workspace_id=payload.workspace_id,
            effective_mode=payload.effective_mode,
            platform_role=payload.platform_role,
            workspace_role=payload.workspace_role,
        )
    except BrowserValidationError as error:
        status_code = 400
        result = {"error": "validation_error", "detail": str(error), "field": error.field}
else:
    status_code, result = handle_action(
        Path(payload.data_root),
        arguments,
        app_id=local_app_id,
        workspace_id=payload.workspace_id,
        effective_mode=payload.effective_mode,
        platform_role=payload.platform_role,
        workspace_role=payload.workspace_role,
    )
result.update({"app_id": local_app_id, "workspace_id": payload.workspace_id, "command_id": command_id, "status_code": status_code})
emit_json(result)
