"""CLI entrypoint for Docs Studio."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from service import (
    docs_manifest,
    docs_read,
    docs_search,
    reference_manifest,
    reference_resolve,
    reference_search,
    reference_summarize,
    state_payload,
    status_payload,
)


payload = read_entrypoint_payload()
command = str(payload.raw.get("command_id") or payload.arguments.get("command") or "docs-studio")
subcommand = str(payload.arguments.get("subcommand") or payload.arguments.get("action") or "status")
if subcommand in {"manifest", "docs-manifest", "toc"}:
    result = docs_manifest(payload, payload.arguments)
elif subcommand in {"search", "docs-search"}:
    result = docs_search(payload, payload.arguments)
elif subcommand in {"read", "get", "docs-read"}:
    result = docs_read(payload, payload.arguments)
elif subcommand == "state":
    result = state_payload(payload)
elif subcommand in {"references", "reference-manifest"}:
    result = {"reference_manifest": reference_manifest()}
elif subcommand == "reference-search":
    result = reference_search(payload, str(payload.arguments.get("query") or ""))
elif subcommand == "reference-resolve":
    result = reference_resolve(payload, str(payload.arguments.get("entity_id") or ""))
elif subcommand == "reference-summarize":
    result = reference_summarize(payload, str(payload.arguments.get("entity_id") or ""))
else:
    result = status_payload(payload)
emit_json({
    "app_id": "docs-studio",
    "workspace_id": payload.workspace_id,
    "command_id": command,
    **result,
})
