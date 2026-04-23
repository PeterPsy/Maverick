"""Workspace-scoped API tokens issued to runtime sessions."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from typing import Any


TOKEN_VERSION = "mvr3rt1"


def issue_workspace_api_token(*, workspace_id: str, runtime_session_id: str) -> str:
    """Build a signed bearer token for one runtime session."""
    payload = {
        "version": TOKEN_VERSION,
        "workspace_id": workspace_id,
        "runtime_session_id": runtime_session_id,
    }
    encoded = _base64_url(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    signature = _sign(encoded)
    return f"{encoded}.{signature}"


def verify_workspace_api_token(token: str) -> dict[str, str] | None:
    """Return token claims when the signature and shape are valid."""
    encoded, separator, signature = token.partition(".")
    if not separator or not encoded or not signature:
        return None
    expected = _sign(encoded)
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        raw = base64.urlsafe_b64decode(_pad_base64(encoded)).decode("utf-8")
        payload: Any = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("version") != TOKEN_VERSION:
        return None
    workspace_id = payload.get("workspace_id")
    runtime_session_id = payload.get("runtime_session_id")
    if not isinstance(workspace_id, str) or not workspace_id:
        return None
    if not isinstance(runtime_session_id, str) or not runtime_session_id:
        return None
    return {
        "workspace_id": workspace_id,
        "runtime_session_id": runtime_session_id,
    }


def _sign(encoded_payload: str) -> str:
    digest = hmac.new(_secret(), encoded_payload.encode("utf-8"), hashlib.sha256).digest()
    return _base64_url(digest)


def _secret() -> bytes:
    configured = os.environ.get("MAVERICK3_RUNTIME_API_SECRET", "").strip()
    return (configured or "maverick-v3-local-runtime-api").encode("utf-8")


def _base64_url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _pad_base64(value: str) -> bytes:
    return (value + "=" * (-len(value) % 4)).encode("ascii")
