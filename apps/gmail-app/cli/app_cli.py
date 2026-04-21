"""Gmail App CLI entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from errors import GmailAppError, GmailAppValidationError
from secret_bridge import resolve_local_app_secrets
from service import handle_action


payload = json.loads(sys.stdin.read() or "{}")
arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
command = str(arguments.get("action") or arguments.get("command") or "connection.status").strip()
workspace_id = str(payload.get("workspace_id") or "default")
aliases = {
    "status": "connection.status",
    "search": "threads.search",
    "thread": "threads.get",
    "references": "references.manifest",
    "reference_manifest": "references.manifest",
    "reference_search": "references.search",
    "reference_resolve": "references.resolve",
    "reference_summarize": "references.summarize",
    "approvals": "audit.recent",
    "audit": "audit.recent",
    "health": "health.check",
}
try:
    status_code, result = handle_action(
        Path(payload["data_root"]),
        {"action": aliases.get(command, command), **arguments},
        workspace_id=workspace_id,
        app_secrets=resolve_local_app_secrets(workspace_id=workspace_id),
    )
except GmailAppValidationError as error:
    status_code, result = 400, {"error": "validation_error", "detail": str(error)}
except GmailAppError as error:
    status_code, result = 502, {"error": "gmail_app_error", "detail": str(error)}

print(json.dumps({"status_code": status_code, "workspace_id": payload.get("workspace_id"), **result}, ensure_ascii=False))
