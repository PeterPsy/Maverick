"""Chat app CLI entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys


def _read_state(data_root: Path) -> dict:
    path = data_root / "threads.json"
    if not path.is_file():
        return {"threads": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"threads": []}
    return payload if isinstance(payload, dict) else {"threads": []}


payload = json.loads(sys.stdin.read() or "{}")
state = _read_state(Path(payload["data_root"]))

print(
    json.dumps(
        {
            "workspace_id": payload["workspace_id"],
            "app_id": payload["app_id"],
            "thread_count": len(state.get("threads", [])),
            "threads": state.get("threads", []),
            "arguments": payload.get("arguments", {}),
        }
    )
)
