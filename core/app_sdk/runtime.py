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
