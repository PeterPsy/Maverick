"""Migration hook for the chat app."""

from __future__ import annotations

import json
from pathlib import Path
import sys


payload = json.loads(sys.stdin.read() or "{}")
data_root = Path(payload["data_root"])
threads_path = data_root / "threads.json"
legacy_path = data_root / "conversations.json"
if threads_path.exists():
    raise SystemExit(0)
if legacy_path.exists():
    legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
    threads_path.write_text(
        json.dumps(
            {
                "schema_version": "2",
                "projects": [],
                "threads": [],
                "preferences": {"active_thread_id": None},
                "legacy_messages": legacy.get("messages", []),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
else:
    threads_path.write_text(
        json.dumps({"schema_version": "2", "projects": [], "threads": [], "preferences": {"active_thread_id": None}}, indent=2) + "\n",
        encoding="utf-8",
    )
