"""Dynamic Views app backend entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from errors import DynamicViewsValidationError
from service import handle_action


def _response(status_code: int, payload: dict) -> None:
    print(json.dumps({"status_code": status_code, "json": payload}, ensure_ascii=False))


def main() -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    body = payload.get("body") if isinstance(payload.get("body"), dict) else {}
    try:
        status_code, result = handle_action(
            Path(payload["data_root"]),
            workspace_id=str(payload.get("workspace_id") or "default"),
            source_instance_id=str(body.get("source_instance_id") or payload.get("runtime_session_id") or "").strip() or None,
            body=body,
        )
    except DynamicViewsValidationError as error:
        _response(400, {"error": "validation_error", "detail": str(error)})
        return
    _response(status_code, result)


if __name__ == "__main__":
    main()
