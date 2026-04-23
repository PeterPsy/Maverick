"""Gmail App backend entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from errors import GmailAppError, GmailAppValidationError
from service import app_events_for_action, handle_action


def main() -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    body = payload.get("body") if isinstance(payload.get("body"), dict) else {}
    app_secrets = payload.get("app_secrets") if isinstance(payload.get("app_secrets"), dict) else {}
    action = str(body.get("action") or "connection.status").strip()
    try:
        status_code, result = handle_action(
            Path(payload["data_root"]),
            body,
            workspace_id=str(payload.get("workspace_id") or "default"),
            app_secrets={str(key): str(value) for key, value in app_secrets.items()},
        )
    except GmailAppValidationError as error:
        status_code, result = 400, {"error": "validation_error", "detail": str(error)}
    except GmailAppError as error:
        status_code, result = 502, {"error": "gmail_app_error", "detail": str(error)}
    secret_writes = result.pop("_platform_secret_writes", []) if isinstance(result, dict) else []
    response = {"status_code": status_code, "json": result, "platform_secret_writes": secret_writes}
    if status_code < 400:
        response["app_events"] = app_events_for_action(action)
    print(json.dumps(response, ensure_ascii=False))


if __name__ == "__main__":
    main()
