"""Dynamic Views app backend entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from errors import DynamicViewsValidationError
from service import app_events_for_action, handle_action


def _response(status_code: int, payload: dict) -> None:
    print(json.dumps({"status_code": status_code, "json": payload}, ensure_ascii=False))


def main() -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    body = payload.get("body") if isinstance(payload.get("body"), dict) else {}
    action = str(body.get("action") or "list").strip().lower()
    workspace_id = str(payload.get("workspace_id") or "").strip()
    if not workspace_id:
        _response(400, {"error": "workspace_id_required"})
        return
    try:
        status_code, result = handle_action(
            Path(payload["data_root"]),
            workspace_id=workspace_id,
            source_instance_id=str(body.get("source_instance_id") or payload.get("runtime_session_id") or "").strip() or None,
            body=body,
        )
    except DynamicViewsValidationError as error:
        _response(400, {"error": "validation_error", "detail": str(error)})
        return
    response = {"status_code": status_code, "json": result}
    if status_code < 400:
        response["app_events"] = app_events_for_action(action)
    print(json.dumps(response, ensure_ascii=False))


if __name__ == "__main__":
    main()
