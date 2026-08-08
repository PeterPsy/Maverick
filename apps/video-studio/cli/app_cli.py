"""CLI entrypoint for `video-studio`."""

from __future__ import annotations

from core.app_sdk.runtime import emit_json, read_entrypoint_payload


payload = read_entrypoint_payload()
emit_json({
    "app_id": "video-studio",
    "workspace_id": payload.workspace_id,
    "command_id": payload.raw.get("command_id"),
    "reference_manifest": {"entity_types": []},
})
