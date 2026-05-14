"""Settings app MCP entrypoint."""

from __future__ import annotations

import json
import sys


payload = json.loads(sys.stdin.read() or "{}")
tool_name = str(payload.get("tool_name") or "")
manifest = {"app_id": "settings", "schema_version": "1", "entity_types": []}

if tool_name == "settings_reference_manifest":
    result = manifest
elif tool_name in {"settings_reference_search", "settings_reference_resolve", "settings_reference_summarize"}:
    result = {"error": "unsupported_reference_operation", "detail": "Settings does not expose referenceable user records in v1."}
else:
    result = {"error": "unsupported_reference_operation", "detail": "Settings does not expose referenceable user records in v1."}

print(json.dumps({"status_code": 200, **result}, ensure_ascii=False))
