"""Speech app CLI entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from errors import SpeechProviderUnavailableError, SpeechTranscriptionError, SpeechValidationError, validation_error_payload
from service import handle_action, operations_manifest


CLI_ACTIONS = {"operations.manifest", "transcribe_file"}
CLI_ARGUMENT_FIELDS = {"action", "workspace_relative_path", "content_type", "language"}


def _response(status_code: int, payload: dict, envelope: dict) -> None:
    response = {
        "status_code": status_code,
        "workspace_id": envelope.get("workspace_id"),
        "app_id": envelope.get("app_id"),
        **payload,
    }
    print(json.dumps(response, ensure_ascii=False))


def _unexpected_fields(arguments: dict) -> list[str]:
    return sorted(set(arguments) - CLI_ARGUMENT_FIELDS)


def _agent_manifest() -> dict:
    manifest = operations_manifest()
    return {
        **manifest,
        "surface": "cli",
        "operations": {
            "operations.manifest": {"description": "Describe Speech CLI operations.", "required_fields": []},
            "transcribe_file": manifest["operations"]["transcribe_file"],
        },
        "notes": [
            "CLI exposes file transcription for workspace Storage audio only.",
            "Inline microphone audio and live streaming are backend/UI surfaces, not CLI surfaces.",
        ],
    }


payload = json.loads(sys.stdin.read() or "{}")
arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
action = str(arguments.get("action") or "operations.manifest").strip()
body = {"action": action, **arguments}
unexpected_fields = _unexpected_fields(arguments)

if action not in CLI_ACTIONS:
    _response(
        400,
        {
            "error": "unsupported_action",
            "action": action,
            "detail": f"Unsupported Speech CLI operation: {action or '<empty>'}.",
            "allowed_values": {"action": sorted(CLI_ACTIONS)},
        },
        payload,
    )
elif unexpected_fields:
    _response(
        400,
        validation_error_payload(
            SpeechValidationError(
                f"Unexpected field(s): {', '.join(unexpected_fields)}.",
                operation=action,
                allowed_values={"fields": sorted(CLI_ARGUMENT_FIELDS)},
            )
        ),
        payload,
    )
elif action == "operations.manifest":
    _response(200, _agent_manifest(), payload)
else:
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
    _response(status_code, result, payload)
