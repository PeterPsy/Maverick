"""Mounted backend entrypoint for `video-studio`."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import backend_response, emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parent))
from project_actions import app_events_for_result, handle_action


def main() -> None:
    payload = read_entrypoint_payload()
    action = str(payload.body.get("action") or "status").strip().lower()
    status_code, result = handle_action(payload.data_root, payload.workspace_id, payload.body)
    result.update({"workspace_id": payload.workspace_id, "surface": "backend"})
    response = backend_response(status_code, result)
    if status_code < 400:
        response["app_events"] = app_events_for_result(action, result)
    emit_json(response)


if __name__ == "__main__":
    main()
