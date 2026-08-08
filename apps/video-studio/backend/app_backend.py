"""Mounted backend entrypoint for `video-studio`."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import backend_response, emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parent))
from service import handle_foundation_action


def main() -> None:
    payload = read_entrypoint_payload()
    action = str(payload.body.get("action") or "status")
    status_code, result = handle_foundation_action(payload.data_root, action)
    result.update({"workspace_id": payload.workspace_id, "surface": "backend"})
    emit_json(backend_response(status_code, result))


if __name__ == "__main__":
    main()
