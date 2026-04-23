"""Skills app CLI entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from service import app_events_for_action, handle_action
from store import SkillsValidationError


payload = json.loads(sys.stdin.read() or "{}")
arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
command = str(payload.get("command_id") or arguments.get("action") or "catalog")
if command == "app.skills.skills":
    command = str(arguments.get("action") or "catalog")
elif command == "app.skills.sync":
    command = "sync_bundled_skills"
try:
    status_code, result = handle_action(
        Path(payload["data_root"]),
        {
            "action": command,
            "repository_root": str(Path(__file__).resolve().parents[3]),
            **arguments,
        },
    )
except SkillsValidationError as error:
    status_code, result = 400, {"error": "validation_error", "detail": str(error)}

response = {"status_code": status_code, "workspace_id": payload.get("workspace_id"), **result}
if status_code < 400:
    response["app_events"] = app_events_for_action(command)
print(json.dumps(response, ensure_ascii=False))
