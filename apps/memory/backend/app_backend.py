"""Memory app backend entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from errors import MemoryValidationError
from service import app_events_for_action, handle_action


def main() -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    body = payload.get("body") if isinstance(payload.get("body"), dict) else {}
    action = str(body.get("action") or "context").strip()
    try:
        status_code, result = handle_action(Path(payload["data_root"]), body)
    except MemoryValidationError as error:
        status_code, result = 400, {"error": "validation_error", "detail": str(error)}
    response = {"status_code": status_code, "json": result}
    if status_code < 400:
        response["app_events"] = app_events_for_action(action)
    print(json.dumps(response, ensure_ascii=False))


if __name__ == "__main__":
    main()
