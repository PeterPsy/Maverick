"""Memory app backend entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys

from errors import MemoryValidationError
from entrypoint_errors import storage_error_response
from service import app_events_for_action, handle_action


def main() -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    body = payload.get("body") if isinstance(payload.get("body"), dict) else {}
    action = str(body.get("action") or "context").strip()
    app_id = str(payload.get("app_id") or "memory")
    try:
        status_code, result = handle_action(Path(payload["data_root"]), body, app_id=app_id)
    except MemoryValidationError as error:
        status_code, result = 400, {"error": "validation_error", "detail": str(error)}
    except sqlite3.Error as error:
        status_code, result = storage_error_response(error, app_id=app_id, action=action)
    event_action = result.pop("_event_action", action) if isinstance(result, dict) else action
    response = {"status_code": status_code, "json": result}
    if status_code < 400:
        response["app_events"] = app_events_for_action(event_action)
    print(json.dumps(response, ensure_ascii=False))


if __name__ == "__main__":
    main()
