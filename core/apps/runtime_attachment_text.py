"""Resolve app-owned document extraction for platform runtime input snapshots."""

from __future__ import annotations

import base64
from pathlib import Path

from core.apps.surfaces import enabled_workspace_app_bindings, resolve_workspace_app_surface
from core.providers.errors import AgenticRuntimeError
from core.shared.entrypoints import run_json_entrypoint


def extract_runtime_attachment_text(state, *, session, filename, raw, max_chars) -> str:
    providers = []
    for binding in enabled_workspace_app_bindings(state.app_store, workspace_id=session.workspace_id):
        source, parsed = resolve_workspace_app_surface(
            state.app_store, binding=binding, start_path=state.repository_root,
        )
        if any(
            item.interface == "runtime.attachment-text" and item.version == "1"
            and "backend" in item.surfaces for item in parsed.contract.provides
        ) and parsed.contract.entrypoints.backend:
            providers.append((source, parsed.contract.entrypoints.backend, binding))
    if len(providers) != 1:
        raise AgenticRuntimeError("research_attachment_extractor_unavailable")
    source, backend, binding = providers[0]
    result = run_json_entrypoint(
        Path(source) / backend,
        payload={
            "surface": "runtime_attachment_text", "workspace_id": session.workspace_id,
            "app_id": binding.app_id, "data_root": binding.data_root,
            "body": {
                "filename": filename, "content_base64": base64.b64encode(raw).decode("ascii"),
                "max_chars": max_chars,
            },
        },
        cwd=Path(source), timeout_seconds=60,
    )
    body = result.get("json", {})
    if (
        result.get("status_code") != 200 or not isinstance(body, dict)
        or not isinstance(body.get("text"), str) or not body["text"].strip()
    ):
        raise AgenticRuntimeError("research_attachment_text_invalid")
    if body.get("truncated"):
        raise AgenticRuntimeError("research_attachment_limit_exceeded")
    return body["text"]
