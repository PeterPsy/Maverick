"""Base Shell app MCP entrypoint."""

from __future__ import annotations

import json
import sys


payload = json.loads(sys.stdin.read() or "{}")
tool_name = str(payload.get("tool_name") or "")
manifest = {"app_id": "base-shell", "schema_version": "1", "entity_types": []}

if tool_name == "base_shell_reference_manifest":
    result = manifest
elif tool_name in {"base_shell_reference_search", "base_shell_reference_resolve", "base_shell_reference_summarize"}:
    result = {"error": "unsupported_reference_operation", "detail": "Base Shell has no referenceable entities."}
else:
    result = {"error": "unsupported_reference_operation", "detail": "Base Shell has no referenceable entities."}

print(json.dumps({"status_code": 200, **result}, ensure_ascii=False))
