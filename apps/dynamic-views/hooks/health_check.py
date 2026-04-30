"""Health check hook for Dynamic Views."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from service import handle_action


payload = json.loads(sys.stdin.read() or "{}")
workspace_id = str(payload.get("workspace_id") or "").strip()
if not workspace_id:
    status_code, result = 400, {"error": "workspace_id_required"}
else:
    status_code, result = handle_action(
        Path(payload["data_root"]),
        workspace_id=workspace_id,
        source_instance_id=None,
        body={"action": "health.check"},
    )
print(json.dumps({"status_code": status_code, **result}, ensure_ascii=False))
