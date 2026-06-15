"""Mounted backend entrypoint for Design Studio."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.app_sdk.runtime import backend_response, emit_json, read_entrypoint_payload
from service import DesignStudioError, dispatch


def main() -> None:
    payload = read_entrypoint_payload()
    action = str(payload.body.get("action") or "state")
    arguments = payload.body.get("arguments", payload.body)
    if not isinstance(arguments, dict):
        arguments = {}
    try:
        result = dispatch(action, payload.raw, arguments)
    except DesignStudioError as error:
        emit_json(backend_response(400, {"error": error.error, "detail": error.detail}))
        return
    response = backend_response(200, result)
    if action in {
        "create_project",
        "import_from_storage",
        "record_storage_import_result",
        "export_to_storage",
        "record_storage_export_result",
        "set_view_filter",
        "set_custom_view",
        "clear_custom_view",
    }:
        response["app_events"] = [
            {
                "type": "maverick.app.data-changed",
                "owner_app_id": payload.app_id or "design-studio",
                "resource": "state",
            },
            {
                "type": "maverick.app.data-changed",
                "owner_app_id": payload.app_id or "design-studio",
                "resource": "view-state",
            },
        ]
    emit_json(response)


if __name__ == "__main__":
    main()
