"""Gmail App MCP entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from errors import GmailAppError, GmailAppValidationError
from secret_bridge import resolve_local_app_secrets
from service import action_from_tool, handle_action


payload = json.loads(sys.stdin.read() or "{}")
arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
action = action_from_tool(str(payload.get("tool_name") or ""), str(arguments.get("action") or "connection.status"))
workspace_id = str(payload.get("workspace_id") or "default")
try:
    status_code, result = handle_action(
        Path(payload["data_root"]),
        {"action": action, **arguments},
        workspace_id=workspace_id,
        app_secrets=resolve_local_app_secrets(workspace_id=workspace_id),
    )
except GmailAppValidationError as error:
    status_code, result = 400, {"error": "validation_error", "detail": str(error)}
except GmailAppError as error:
    status_code, result = 502, {"error": "gmail_app_error", "detail": str(error)}

print(json.dumps({"status_code": status_code, **result}, ensure_ascii=False))
