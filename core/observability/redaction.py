"""Redaction helpers for observability payloads."""

from __future__ import annotations


SENSITIVE_KEYS = {
    "secret",
    "secret_ref",
    "secret_refs",
    "token",
    "api_key",
    "password",
    "authorization",
    "raw_value",
    "env_overrides",
}


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).lower()
    return normalized in SENSITIVE_KEYS or normalized.endswith("_secret_ref") or normalized.endswith("_secret_refs")


def redact_payload(payload):
    """Recursively redact sensitive payload fields for logs, audit, and events."""
    if isinstance(payload, dict):
        redacted = {}
        for key, value in payload.items():
            if _is_sensitive_key(key):
                redacted[key] = "<redacted>"
            else:
                redacted[key] = redact_payload(value)
        return redacted
    if isinstance(payload, list):
        return [redact_payload(item) for item in payload]
    return payload
