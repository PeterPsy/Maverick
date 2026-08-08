"""MCP entrypoint for `video-studio`."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from service import handle_foundation_action


def main() -> None:
    payload = read_entrypoint_payload()
    tool_name = str(payload.raw.get("tool_name") or "")
    if tool_name == "video_studio_reference_manifest":
        status_code, result = 200, {"ok": True, "entity_types": []}
    elif tool_name != "video_studio_foundation":
        status_code, result = 400, {
            "ok": False,
            "error": {"code": "unsupported_tool", "message": "Unsupported Video Studio tool."},
        }
    else:
        status_code, result = handle_foundation_action(
            payload.data_root,
            str(payload.arguments.get("action") or "status"),
        )
    result.update({
        "app_id": "video-studio",
        "workspace_id": payload.workspace_id,
        "tool_name": tool_name,
        "status_code": status_code,
        "surface": "mcp",
    })
    emit_json(result)


if __name__ == "__main__":
    main()
