"""Signed context tokens for iframe-mounted app widgets."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from typing import Any


def _secret() -> bytes:
    return os.environ.get("MAVERICK3_WIDGET_CONTEXT_SECRET", "maverick3-dev-widget-context").encode("utf-8")


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
