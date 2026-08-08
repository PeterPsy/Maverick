"""CLI entrypoint for `video-studio`."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from service import handle_foundation_action


def main() -> None:
    payload = read_entrypoint_payload()
    command_id = str(payload.raw.get("command_id") or "")
    command_name = command_id.rsplit(".", 1)[-1]
    if command_name != "video-studio":
        status_code, result = 400, {
            "ok": False,
            "error": {"code": "unsupported_command", "message": "Unsupported Video Studio command."},
        }
    else:
        status_code, result = handle_foundation_action(
            payload.data_root,
            str(payload.arguments.get("action") or "status"),
        )
    result.update({
        "app_id": "video-studio",
        "workspace_id": payload.workspace_id,
        "command_id": command_id,
        "status_code": status_code,
        "surface": "cli",
    })
    emit_json(result)


if __name__ == "__main__":
    main()
