"""CLI entrypoint for Maverick Monitor."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from service import app_events_for_action, handle_action


def main() -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
    workspace_root = Path(payload.get("workspace_root") or ".").resolve()
    data_root = Path(payload.get("data_root") or workspace_root / "data" / "maverick-monitor")
    action = str(arguments.get("action") or "snapshot")
    status_code, result = handle_action(workspace_root=workspace_root, data_root=data_root, body={**arguments, "action": action})
    response = {"status_code": status_code, "json": result}
    if status_code < 400:
        response["app_events"] = app_events_for_action(action)
    print(json.dumps(response, ensure_ascii=False))


if __name__ == "__main__":
    main()
