"""Base Shell app CLI entrypoint."""

from __future__ import annotations

import json
import sys


payload = json.loads(sys.stdin.read() or "{}")
arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
action = str(arguments.get("action") or "references.manifest")

manifest = {"app_id": "base-shell", "schema_version": "1", "entity_types": []}
if action == "references.manifest":
    result = manifest
else:
    result = {"error": "unsupported_reference_operation", "detail": "Base Shell has no referenceable entities."}

print(json.dumps({"status_code": 200, "workspace_id": payload.get("workspace_id"), **result}, ensure_ascii=False))

