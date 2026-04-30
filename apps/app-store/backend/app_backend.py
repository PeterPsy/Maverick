"""App Store app backend entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from service import AppStoreValidationError, app_events_for_action, handle_action


def _response(status_code: int, payload: dict) -> None:
    print(json.dumps({"status_code": status_code, "json": payload}, ensure_ascii=False))


def main() -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    body = payload.get("body") if isinstance(payload.get("body"), dict) else {}
    action = str(body.get("action") or "catalog")
    try:
        workspace_root = Path(payload["workspace_root"]) if payload.get("workspace_root") else None
        status_code, result = handle_action(Path(payload["data_root"]), body, workspace_root=workspace_root)
    except AppStoreValidationError as error:
        _response(400, {"error": "validation_error", "detail": str(error)})
        return
    except Exception as error:
        _response(502, {"error": "catalog_unavailable", "detail": str(error)})
        return
    response = {"status_code": status_code, "json": result}
    if status_code < 400:
        response["app_events"] = app_events_for_action(action)
    print(json.dumps(response, ensure_ascii=False))


if __name__ == "__main__":
    main()
