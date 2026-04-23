"""Agents app backend entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from service import app_events_for_action, handle_action
from store import AgentsValidationError


def _response(status_code: int, payload: dict) -> None:
    print(json.dumps({"status_code": status_code, "json": payload}, ensure_ascii=False))


def main() -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    body = payload.get("body") if isinstance(payload.get("body"), dict) else {}
    data_root = Path(payload["data_root"])
    action = str(body.get("action") or "catalog")
    try:
        status_code, result = handle_action(data_root, body)
    except AgentsValidationError as error:
        _response(400, {"error": "validation_error", "detail": str(error)})
        return
    response = {"status_code": status_code, "json": result}
    if status_code < 400:
        response["app_events"] = app_events_for_action(action)
    print(json.dumps(response, ensure_ascii=False))


if __name__ == "__main__":
    main()
