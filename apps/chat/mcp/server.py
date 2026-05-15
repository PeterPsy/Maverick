"""Chat app MCP entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from service import ChatValidationError, app_events_for_result, handle_action, unsupported_action_payload, validation_error_payload


payload = json.loads(sys.stdin.read() or "{}")
arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
tool_name = str(payload.get("tool_name") or "")
tool_actions = {
    "chat_operations_manifest": "operations.manifest",
    "chat_reference_manifest": "references.manifest",
    "chat_reference_search": "references.search",
    "chat_reference_resolve": "references.resolve",
    "chat_reference_summarize": "references.summarize",
    "chat_view_filter": "view_filter",
    "chat_set_view_filter": "set_view_filter",
    "chat_set_custom_view": "set_custom_view",
    "chat_clear_custom_view": "clear_custom_view",
}
tool_argument_fields = {
    "chat_operations_manifest": set(),
    "chat_reference_manifest": set(),
    "chat_reference_search": {"entity_type", "type", "query", "q", "limit"},
    "chat_reference_resolve": {"entity_type", "type", "entity_id", "project_id", "id"},
    "chat_reference_summarize": {"entity_type", "type", "entity_id", "project_id", "id"},
    "chat_view_filter": set(),
    "chat_set_view_filter": {"query", "entity_type", "preserve_custom"},
    "chat_set_custom_view": {"title", "query", "entity_type", "refs"},
    "chat_clear_custom_view": set(),
}


def _unexpected_tool_fields(tool: str, args: dict) -> list[str]:
    allowed = tool_argument_fields.get(tool)
    if allowed is None:
        return []
    return sorted(set(args) - allowed)


action = tool_actions.get(tool_name)
if action is None:
    status_code, result = 400, unsupported_action_payload(tool_name)
else:
    unexpected_fields = _unexpected_tool_fields(tool_name, arguments)
    if unexpected_fields:
        status_code, result = 400, validation_error_payload(
            ChatValidationError(
                f"Unexpected field(s): {', '.join(unexpected_fields)}.",
                allowed_values={"fields": sorted(tool_argument_fields[tool_name])},
                example={},
            ),
            action,
        )
    else:
        body = {"action": action, **arguments}
        try:
            status_code, result = handle_action(Path(payload["data_root"]), body)
        except ChatValidationError as error:
            status_code, result = 400, validation_error_payload(error, action)

response = {"status_code": status_code, **result}
if status_code < 400:
    response["app_events"] = app_events_for_result(action or "", result)
print(json.dumps(response, ensure_ascii=False))
