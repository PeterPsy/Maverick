"""Signed context tokens for iframe-mounted app widgets."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from typing import Any

from core.secrets.bootstrap import resolve_bootstrap_secret


def _secret() -> bytes:
    configured_ref = os.environ.get("MAVERICK_WIDGET_CONTEXT_SECRET_REF", "").strip()
    if configured_ref:
        return resolve_bootstrap_secret(configured_ref).encode("utf-8")
    configured = os.environ.get("MAVERICK_WIDGET_CONTEXT_SECRET", "").strip()
    if configured:
        return configured.encode("utf-8")
    if os.environ.get("MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS") == "1":
        return b"maverick-dev-widget-context"
    raise RuntimeError("MAVERICK_WIDGET_CONTEXT_SECRET_REF or MAVERICK_WIDGET_CONTEXT_SECRET is required.")


def _encode_json(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_json(payload: str) -> dict[str, Any]:
    padding = "=" * (-len(payload) % 4)
    raw = base64.urlsafe_b64decode((payload + padding).encode("ascii"))
    decoded = json.loads(raw.decode("utf-8"))
    return decoded if isinstance(decoded, dict) else {}


def sign_widget_context(context: dict[str, Any]) -> str:
    """Return a signed opaque token for explicit widget bootstrap context."""
    payload = _encode_json(context)
    signature = hmac.new(_secret(), payload.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def verify_widget_context(token: str) -> dict[str, Any] | None:
    """Verify and decode a widget context token."""
    payload, separator, signature = token.partition(".")
    if not separator:
        return None
    expected = hmac.new(_secret(), payload.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    return _decode_json(payload)
