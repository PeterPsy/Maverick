"""Health check hook for the Document Generator app."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from service import handle_action


payload = json.loads(sys.stdin.read() or "{}")
status_code, result = handle_action(
    Path(payload["data_root"]),
    Path(payload["generated_storage_root"]),
    {"action": "health.check"},
)
print(json.dumps({"status_code": status_code, **result}, ensure_ascii=False))
