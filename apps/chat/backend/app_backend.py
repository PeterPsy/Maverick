"""Chat app backend entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from service import ChatValidationError, app_events_for_result, handle_action, validation_error_payload


def _response(status_code: int, payload: dict, *, action: str) -> None:
    response = {"status_code": status_code, "json": payload}
    if status_code < 400:
        response["app_events"] = app_events_for_result(action, payload)
    print(json.dumps(response, ensure_ascii=False))


def _runtime_cleanup_then_commit_response(payload: dict) -> None:
    response = {
        "status_code": 200,
        "json": {"project_id": payload["project_id"]},
        "runtime_cleanup_requests": payload["runtime_cleanup_requests"],
        "runtime_cleanup_commit": payload["runtime_cleanup_commit"],
    }
    print(json.dumps(response, ensure_ascii=False))


def main() -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    body = payload.get("body") if isinstance(payload.get("body"), dict) else {}
    action = str(body.get("action") or "projects.list")
    data_root = Path(payload["data_root"])

    try:
        status_code, result = handle_action(
            data_root,
            body,
            invocation_surface=str(payload.get("surface") or ""),
        )
    except ChatValidationError as error:
        status_code, result = 400, validation_error_payload(error, action)

    if status_code < 400 and result.get("runtime_cleanup_requests"):
        _runtime_cleanup_then_commit_response(result)
        return
    _response(status_code, result, action="projects.delete" if action == "projects.delete.commit" else action)


if __name__ == "__main__":
    main()
