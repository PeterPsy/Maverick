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

print(
    json.dumps(
        {
            "workspace_id": payload["workspace_id"],
            "app_id": payload["app_id"],
            "message_count": len(state.get("messages", [])),
            "arguments": payload.get("arguments", {}),
        }
    )
)
