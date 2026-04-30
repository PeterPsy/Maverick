"""User Admin app MCP entrypoint."""

from __future__ import annotations

import json
import sys


payload = json.loads(sys.stdin.read() or "{}")
tool_name = str(payload.get("tool_name") or "")
manifest = {"app_id": "user-admin", "schema_version": "1", "entity_types": []}

if tool_name == "user_admin_reference_manifest":
    result = manifest
elif tool_name in {"user_admin_reference_search", "user_admin_reference_resolve", "user_admin_reference_summarize"}:
    result = {"error": "unsupported_reference_operation", "detail": "User Admin does not expose referenceable user records in v1."}
else:
    result = {"error": "unsupported_reference_operation", "detail": "User Admin does not expose referenceable user records in v1."}

print(json.dumps({"status_code": 200, **result}, ensure_ascii=False))
