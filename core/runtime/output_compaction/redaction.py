"""Text and structure redaction for runtime tool output."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any


REDACTED = "<redacted>"

SENSITIVE_KEY_PARTS = (
    "authorization",
    "api_key",
    "apikey",
    "access_key",
    "secret",
    "token",
    "password",
    "passwd",
    "cookie",
    "private_key",
    "raw_value",
)

_PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    re.IGNORECASE | re.DOTALL,
)
_AUTHORIZATION_PATTERN = re.compile(r"(?i)(authorization\s*:\s*)(bearer|basic)\s+[^;\s\r\n]+")
_COOKIE_LINE_PATTERN = re.compile(r"(?im)^(set-cookie|cookie)\s*:\s*.+$")
_QUERY_SECRET_PATTERN = re.compile(
    r"(?i)([?&](?:token|access_token|refresh_token|api_key|apikey|key|secret|password|code)=)([^&#\s]+)"
)
_ENV_SECRET_PATTERN = re.compile(
    r"(?im)^([A-Z0-9_]*(?:TOKEN|PASSWORD|PASSWD|API_KEY|SECRET|PRIVATE_KEY|ACCESS_KEY|AUTH)[A-Z0-9_]*\s*=\s*)[^\s#]+"
)
_JWT_PATTERN = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")
_URL_CREDENTIAL_PATTERN = re.compile(r"([a-z][a-z0-9+.-]*://)([^/\s:@]+):([^@\s/]+)@", re.IGNORECASE)
_KNOWN_API_KEY_PATTERN = re.compile(r"\b(?:sk|pk|rk|ghp|github_pat)_[A-Za-z0-9_=-]{16,}\b")
_OPENAI_STYLE_KEY_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")


def is_sensitive_key(key: object) -> bool:
    """Return true when a structured key should not persist a raw value."""
    normalized = str(key).replace("-", "_").lower()
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def redact_text(value: str) -> str:
    """Redact common secrets from free-form tool output text."""
    text = str(value)
    substitutions = (
        (_PRIVATE_KEY_PATTERN, REDACTED),
        (_AUTHORIZATION_PATTERN, rf"\1\2 {REDACTED}"),
        (_COOKIE_LINE_PATTERN, rf"\1: {REDACTED}"),
        (_QUERY_SECRET_PATTERN, rf"\1{REDACTED}"),
        (_ENV_SECRET_PATTERN, rf"\1{REDACTED}"),
        (_JWT_PATTERN, REDACTED),
        (_URL_CREDENTIAL_PATTERN, rf"\1{REDACTED}@"),
        (_KNOWN_API_KEY_PATTERN, REDACTED),
        (_OPENAI_STYLE_KEY_PATTERN, REDACTED),
    )
    for pattern, replacement in substitutions:
        try:
            text = pattern.sub(replacement, text)
        except re.error:
            continue
    return text


def redact_payload(value: Any) -> Any:
    """Recursively redact structured values and free-form strings."""
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if is_sensitive_key(key):
                result[str(key)] = REDACTED
                continue
            result[str(key)] = redact_payload(item)
        return result
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return [redact_payload(item) for item in value]
    return value
