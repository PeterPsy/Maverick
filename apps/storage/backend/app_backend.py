"""Storage app backend entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from errors import StorageValidationError, validation_error_payload
from operations_manifest import STORAGE_ACTION_ALIASES
from service import app_events_for_action, handle_action


def _response(status_code: int, payload: dict) -> None:
    print(json.dumps({"status_code": status_code, "json": payload}, ensure_ascii=False))


def main() -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    body = payload.get("body") if isinstance(payload.get("body"), dict) else {}
    body = {
        **body,
        "_app_secrets": payload.get("app_secrets", {}),
        "_workspace_id": payload.get("workspace_id") or "default",
        "_app_id": payload.get("app_id") or "storage",
    }
    requested_action = str(body.get("action") or "catalog")
    action = STORAGE_ACTION_ALIASES.get(requested_action, requested_action)
    body = {**body, "action": action}
    try:
        status_code, result = handle_action(
            Path(payload["data_root"]),
            Path(payload["uploaded_storage_root"]),
            Path(payload["generated_storage_root"]),
            body,
            allow_platform_secret_writes=True,
        )
    except StorageValidationError as error:
        _response(400, validation_error_payload(error))
        return
    platform_secret_writes = result.pop("platform_secret_writes", None)
    response = {"status_code": status_code, "json": result}
    if platform_secret_writes is not None:
        response["platform_secret_writes"] = platform_secret_writes
    if status_code < 400:
        response["app_events"] = app_events_for_action(action)
    print(json.dumps(response, ensure_ascii=False))


if __name__ == "__main__":
    main()
