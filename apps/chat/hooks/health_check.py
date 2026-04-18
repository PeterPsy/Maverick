import json
from pathlib import Path
import sys


payload = json.loads(sys.stdin.read() or "{}")
data_root = Path(payload["data_root"])
messages_path = data_root / "conversations.json"
if not messages_path.is_file():
    raise SystemExit(1)
json.loads(messages_path.read_text(encoding="utf-8"))
