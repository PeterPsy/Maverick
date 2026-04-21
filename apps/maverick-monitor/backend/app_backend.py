"""Maverick Monitor app backend entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from errors import MonitorValidationError
from service import handle_action


def _response(status_code: int, payload: dict) -> None:
    print(json.dumps({"status_code": status_code, "json": payload}, ensure_ascii=False))


def main() -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    body = payload.get("body") if isinstance(payload.get("body"), dict) else {}
    try:
        status_code, result = handle_action(
            workspace_root=Path(payload["workspace_root"]),
            data_root=Path(payload["data_root"]),
            body=body,
        )
    except MonitorValidationError as error:
        _response(400, {"error": "validation_error", "detail": str(error)})
        return
    _response(status_code, result)


if __name__ == "__main__":
    main()
