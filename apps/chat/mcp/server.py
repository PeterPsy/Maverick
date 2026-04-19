"""Chat app MCP entrypoint."""

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
tool_name = str(payload.get("tool_name") or "")

if tool_name == "threads.list":
    result = {"threads": state.get("threads", [])}
elif tool_name == "message.send":
    result = {
        "accepted": False,
        "reason": "Use the core runtime HTTP surface for live chat messages in the first v3 hosted implementation.",
    }
elif tool_name == "turn.stop":
    result = {"accepted": False, "reason": "Use the core runtime interrupt surface."}
else:
    result = {"accepted": False, "tool_name": tool_name}

print(json.dumps(result))
