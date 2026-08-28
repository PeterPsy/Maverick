"""Mounted Design Studio orchestration surface outside native OpenDesign."""

from __future__ import annotations

from core.app_sdk.runtime import backend_response, emit_json, read_entrypoint_payload

from delegation_errors import DelegationError
from surface_service import SurfaceService, app_events_for_action


def main() -> None:
    payload = read_entrypoint_payload()
    arguments = dict(payload.body)
    action = str(arguments.pop("action", "") or "state")
    try:
        result = SurfaceService(payload).dispatch(action, arguments)
    except DelegationError as error:
        emit_json(
            backend_response(
                error.status_code,
                {"ok": False, "error": error.code, "detail": error.detail},
            )
        )
        return
    response = backend_response(200, {"ok": True, **result})
    response["app_events"] = app_events_for_action(action)
    emit_json(response)


if __name__ == "__main__":
    main()
