"""Redaction helpers for observability payloads."""

from __future__ import annotations


SENSITIVE_KEYS = {"secret", "secret_ref", "token", "api_key", "password", "authorization", "raw_value", "env_overrides"}


def redact_payload(payload):
    """Recursively redact sensitive payload fields for logs, audit, and events."""
    if isinstance(payload, dict):
        redacted = {}
        for key, value in payload.items():
            if str(key).lower() in SENSITIVE_KEYS:
                redacted[key] = "<redacted>"
            else:
                redacted[key] = redact_payload(value)
        return redacted
    if isinstance(payload, list):
        return [redact_payload(item) for item in payload]
    return payload
