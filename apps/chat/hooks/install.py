"""Install hook for the chat app."""

from __future__ import annotations

import json
from pathlib import Path
import sys


payload = json.loads(sys.stdin.read() or "{}")
data_root = Path(payload["data_root"])
data_root.mkdir(parents=True, exist_ok=True)
threads_path = data_root / "threads.json"
if not threads_path.exists():
    threads_path.write_text(
        json.dumps({"schema_version": "2", "projects": [], "threads": [], "preferences": {"active_thread_id": None}}, indent=2) + "\n",
        encoding="utf-8",
    )
