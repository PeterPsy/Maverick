"""MCP entrypoint for external delegation into native OpenDesign."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from core.app_sdk.runtime import emit_json, read_entrypoint_payload
from delegation_errors import DelegationError
from surface_service import SurfaceService, app_events_for_action


TOOL_ACTIONS = {
    "design_studio_delegate": "delegate",
    "design_studio_delegation_status": "delegation_status",
    "design_studio_cancel_delegation": "cancel_delegation",
    "design_studio_delegation_result": "delegation_result",
    "design_studio_state": "state",
    "design_studio_view_filter": "view_filter",
    "design_studio_set_view_filter": "set_view_filter",
    "design_studio_set_custom_view": "set_custom_view",
    "design_studio_clear_custom_view": "clear_custom_view",
}


def main() -> None:
    payload = read_entrypoint_payload()
    tool_name = str(payload.raw.get("tool_name") or "")
    action = TOOL_ACTIONS.get(tool_name)
    if action is None:
        emit_json({
            "status_code": 400,
            "ok": False,
            "error": "unsupported_tool",
            "detail": f"Unsupported Design Studio tool `{tool_name}`.",
        })
        return
    try:
        result = SurfaceService(payload).dispatch(action, dict(payload.arguments))
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
