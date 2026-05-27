"""Small runtime helpers for SDK-generated app entrypoints."""

from __future__ import annotations

from dataclasses import dataclass
import json
import sys
from typing import Any


@dataclass(frozen=True)
class AppEntrypointPayload:
    """Normalized payload passed to app backend, CLI, MCP, and hook entrypoints."""

    raw: dict[str, Any]
    app_id: str
    workspace_id: str | None
    data_root: str
    workspace_root: str | None
    effective_mode: str | None
    platform_role: str | None
    user_id: str | None
    workspace_role: str | None
    runtime_session_id: str | None
    body: dict[str, Any]
    arguments: dict[str, Any]


def read_entrypoint_payload() -> AppEntrypointPayload:
    """Read one JSON stdin payload emitted by the Maverick core host."""
    raw_payload = json.loads(sys.stdin.read() or "{}")
    if not isinstance(raw_payload, dict):
        raise ValueError("Entrypoint payload must be a JSON object.")
    body = raw_payload.get("body", {})
    arguments = raw_payload.get("arguments", {})
    if not isinstance(body, dict):
        raise ValueError("Entrypoint body must be a JSON object.")
    if not isinstance(arguments, dict):
        raise ValueError("Entrypoint arguments must be a JSON object.")
    return AppEntrypointPayload(
        raw=raw_payload,
        app_id=str(raw_payload.get("app_id") or ""),
        workspace_id=raw_payload.get("workspace_id"),
        data_root=str(raw_payload.get("data_root") or ""),
        workspace_root=raw_payload.get("workspace_root"),
        effective_mode=raw_payload.get("effective_mode"),
        platform_role=raw_payload.get("platform_role"),
        user_id=raw_payload.get("user_id"),
        workspace_role=raw_payload.get("workspace_role"),
        runtime_session_id=raw_payload.get("runtime_session_id"),
        body=body,
        arguments=arguments,
    )


def emit_json(payload: dict[str, Any]) -> None:
    """Emit one JSON object to stdout for the core host."""
    sys.stdout.write(json.dumps(payload, ensure_ascii=True))


def backend_response(status_code: int, payload: dict[str, Any]) -> dict[str, Any]:
    """Build a mounted backend response."""
    return {"status_code": status_code, "json": payload}


def ok(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a generic successful entrypoint response."""
    return {"ok": True, **(payload or {})}


def unsupported(action: str) -> dict[str, Any]:
    """Build a consistent unsupported-action response."""
    return {"ok": False, "error": f"Unsupported action `{action}`."}
