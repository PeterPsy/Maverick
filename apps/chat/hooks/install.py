import json
from pathlib import Path
import sys


payload = json.loads(sys.stdin.read() or "{}")
data_root = Path(payload["data_root"])
data_root.mkdir(parents=True, exist_ok=True)
messages_path = data_root / "conversations.json"
if not messages_path.exists():
    messages_path.write_text(json.dumps({"messages": []}, indent=2) + "\n", encoding="utf-8")
