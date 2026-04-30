"""MCP entrypoint for Docs Studio."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from service import (
    clear_custom_view,
    docs_manifest,
    docs_read,
    docs_search,
    reference_manifest,
    reference_resolve,
    reference_search,
    reference_summarize,
    set_custom_view,
    set_view_filter,
    state_payload,
    status_payload,
    view_filter,
)


payload = read_entrypoint_payload()
tool_name = str(payload.raw.get("tool_name") or "")
local_tool_name = tool_name.rsplit(".", 1)[-1]
raw_payload = payload.raw.get("payload")
tool_input = {
    **payload.arguments,
    **payload.body,
    **(raw_payload if isinstance(raw_payload, dict) else {}),
}
if local_tool_name == "docs_studio_reference_manifest":
    result = {"reference_manifest": reference_manifest()}
elif local_tool_name == "docs_studio_docs_manifest":
    result = docs_manifest(payload, tool_input)
elif local_tool_name == "docs_studio_docs_search":
    result = docs_search(payload, tool_input)
elif local_tool_name == "docs_studio_docs_read":
    result = docs_read(payload, tool_input)
elif local_tool_name == "docs_studio_reference_search":
    query = str(tool_input.get("query") or "")
    result = reference_search(payload, query)
elif local_tool_name == "docs_studio_reference_resolve":
    entity_id = str(tool_input.get("entity_id") or "")
    result = reference_resolve(payload, entity_id)
elif local_tool_name == "docs_studio_reference_summarize":
    entity_id = str(tool_input.get("entity_id") or "")
    result = reference_summarize(payload, entity_id)
elif local_tool_name == "docs_studio_state":
    result = state_payload(payload)
elif local_tool_name == "docs_studio_view_filter":
    result = view_filter(payload)
elif local_tool_name == "docs_studio_set_view_filter":
    result = set_view_filter(payload, tool_input)
elif local_tool_name == "docs_studio_set_custom_view":
    page_ids = tool_input.get("page_ids") or []
    result = set_custom_view(payload, page_ids if isinstance(page_ids, list) else [])
elif local_tool_name == "docs_studio_clear_custom_view":
    result = clear_custom_view(payload)
else:
    result = status_payload(payload)
emit_json({
    "app_id": "docs-studio",
    "workspace_id": payload.workspace_id,
    "tool_name": tool_name,
    **result,
})
