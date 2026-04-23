"""Document Generator app backend entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from errors import DocumentValidationError
from service import app_events_for_action, handle_action


def _response(status_code: int, payload: dict) -> None:
    print(json.dumps({"status_code": status_code, "json": payload}, ensure_ascii=False))


def main() -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    body = payload.get("body") if isinstance(payload.get("body"), dict) else {}
    action = str(body.get("action") or "generate_document")
    try:
        status_code, result = handle_action(Path(payload["data_root"]), Path(payload["generated_storage_root"]), body)
    except DocumentValidationError as error:
        _response(400, {"error": "validation_error", "detail": str(error)})
        return
    response = {"status_code": status_code, "json": result}
    if status_code < 400:
        response["app_events"] = app_events_for_action(action)
    print(json.dumps(response, ensure_ascii=False))


if __name__ == "__main__":
    main()
