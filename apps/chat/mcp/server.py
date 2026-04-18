import json
from pathlib import Path
import sys


payload = json.loads(sys.stdin.read() or "{}")
data_root = Path(payload["data_root"])
messages_path = data_root / "conversations.json"
if messages_path.is_file():
    state = json.loads(messages_path.read_text(encoding="utf-8"))
else:
    state = {"messages": []}

tool_name = payload.get("tool_name")
if tool_name == "threads.list":
    result = {
        "thread_count": 1 if state.get("messages") else 0,
        "message_count": len(state.get("messages", [])),
    }
elif tool_name == "message.send":
    message = payload.get("arguments", {}).get("message", "")
    result = {
        "accepted": True,
        "echo": message,
        "workspace_id": payload.get("workspace_id"),
    }
else:
    result = {"accepted": False, "tool_name": tool_name}

print(json.dumps(result))
