"""Chat app CLI entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from service import ChatValidationError, app_events_for_result, handle_action, unsupported_action_payload, validation_error_payload
from surface_manifest import OPERATIONS_MANIFEST

CLI_ACTIONS = ["operations.manifest", *OPERATIONS_MANIFEST["operations"], "learning.read", "learning.discard_all"]
CLI_ARGUMENT_FIELDS = {
    "action",
    "entity_type",
    "type",
    "entity_id",
    "project_id",
    "thread_id",
    "id",
    "query",
    "q",
    "limit",
    "preserve_custom",
    "title",
    "refs",
}


def _unexpected_cli_fields(arguments: dict) -> list[str]:
    return sorted(set(arguments) - CLI_ARGUMENT_FIELDS)


payload = json.loads(sys.stdin.read() or "{}")
arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
action = str(arguments.get("action") or "operations.manifest").strip()
body = {"action": action, **arguments}
unexpected_fields = _unexpected_cli_fields(arguments)
if action not in CLI_ACTIONS:
    status_code, result = 400, unsupported_action_payload(action, allowed_actions=CLI_ACTIONS)
elif unexpected_fields:
    status_code, result = 400, validation_error_payload(
        ChatValidationError(
            f"Unexpected field(s): {', '.join(unexpected_fields)}.",
            allowed_values={"fields": sorted(CLI_ARGUMENT_FIELDS)},
            example={"action": "operations.manifest"},
        ),
        action,
    )
else:
    try:
        if action.startswith("learning."):
            from learning_service import handle_learning
            result = handle_learning({**payload, "body": body})
            changed = result.pop("_changed", False)
            response = {"status_code": 200, "workspace_id": payload.get("workspace_id"), "app_id": payload.get("app_id"), **result}
            if changed:
                response["app_events"] = [{"type": "maverick.app.data-changed", "resource": "learning"}]
            print(json.dumps(response, ensure_ascii=False))
            sys.exit(0)
        status_code, result = handle_action(Path(payload["data_root"]), body)
    except ChatValidationError as error:
        status_code, result = 400, validation_error_payload(error, action)
    except PermissionError as error:
        status_code, result = 403, {"error": str(error)}
    except ValueError as error:
        status_code, result = 400, {"error": str(error)}

response = {
    "status_code": status_code,
    "workspace_id": payload.get("workspace_id"),
    "app_id": payload.get("app_id"),
    **result,
}
if status_code < 400:
    response["app_events"] = app_events_for_result(action, result)
print(json.dumps(response, ensure_ascii=False))
