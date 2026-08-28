"""CLI entrypoint for native Design Studio delegation and inspection."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from core.app_sdk.runtime import emit_json, read_entrypoint_payload
from delegation_errors import DelegationError
from surface_service import SurfaceService, app_events_for_action


def main() -> None:
    payload = read_entrypoint_payload()
    arguments = dict(payload.arguments)
    action = str(arguments.pop("action", "") or "state")
    try:
        result = SurfaceService(payload).dispatch(action, arguments)
    except DelegationError as error:
        emit_json({
            "status_code": error.status_code,
            "ok": False,
            "error": error.code,
            "detail": error.detail,
        })
        return
    emit_json({
        "status_code": 200,
        "ok": True,
        **result,
        "app_events": app_events_for_action(action),
    })


if __name__ == "__main__":
    main()
