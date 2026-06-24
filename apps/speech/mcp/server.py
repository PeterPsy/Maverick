"""Speech app MCP entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from errors import SpeechProviderUnavailableError, SpeechTranscriptionError, SpeechValidationError, validation_error_payload
from service import handle_action, operations_manifest


TOOL_ACTIONS = {
    "speech_operations_manifest": "operations.manifest",
    "speech_reference_manifest": "references.manifest",
    "speech_transcribe_file": "transcribe_file",
}
TOOL_ARGUMENT_FIELDS = {
    "speech_operations_manifest": set(),
    "speech_reference_manifest": set(),
    "speech_transcribe_file": {"workspace_relative_path", "content_type", "language"},
}


def _unexpected_fields(tool_name: str, arguments: dict) -> list[str]:
    return sorted(set(arguments) - TOOL_ARGUMENT_FIELDS.get(tool_name, set()))


def _agent_manifest() -> dict:
    manifest = operations_manifest()
    return {
        **manifest,
        "surface": "mcp",
        "operations": {
            "operations.manifest": {"description": "Describe Speech MCP operations.", "required_fields": []},
            "references.manifest": {"description": "Report that Speech exposes no reference entities.", "required_fields": []},
            "transcribe_file": manifest["operations"]["transcribe_file"],
        },
        "notes": [
            "MCP exposes file transcription for workspace Storage audio only.",
            "Inline microphone audio and live streaming are backend/UI surfaces, not MCP surfaces.",
        ],
    }


payload = json.loads(sys.stdin.read() or "{}")
arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
tool_name = str(payload.get("tool_name") or "").strip()
action = TOOL_ACTIONS.get(tool_name)

if action is None:
    status_code, result = 400, {
        "error": "unsupported_tool",
        "tool_name": tool_name,
        "detail": f"Unsupported Speech MCP tool: {tool_name or '<empty>'}.",
        "allowed_values": {"tool_name": sorted(TOOL_ACTIONS)},
    }
else:
    unexpected_fields = _unexpected_fields(tool_name, arguments)
    if unexpected_fields:
        status_code, result = 400, validation_error_payload(
            SpeechValidationError(
                f"Unexpected field(s): {', '.join(unexpected_fields)}.",
                operation=action,
                allowed_values={"fields": sorted(TOOL_ARGUMENT_FIELDS[tool_name])},
            )
        )
    elif action == "operations.manifest":
        status_code, result = 200, _agent_manifest()
    elif action == "references.manifest":
        status_code, result = 200, {
            "app_id": "speech",
            "schema_version": "1",
            "entity_types": [],
        }
    else:
        body = {"action": action, **arguments}
        if isinstance(payload.get("app_secrets"), dict):
            body["_app_secrets"] = dict(payload["app_secrets"])
        try:
            uploaded_root = Path(payload["uploaded_storage_root"]) if payload.get("uploaded_storage_root") else None
            status_code, result = handle_action(
                Path(payload["data_root"]),
                Path(payload["generated_storage_root"]),
                body,
                uploaded_root,
            )
        except SpeechValidationError as error:
            status_code, result = 400, validation_error_payload(error)
        except SpeechProviderUnavailableError as error:
            status_code, result = 503, {"error": "provider_unavailable", "detail": str(error)}
        except SpeechTranscriptionError as error:
            status_code, result = 502, {"error": "transcription_failed", "detail": str(error)}

print(json.dumps({"status_code": status_code, **result}, ensure_ascii=False))
