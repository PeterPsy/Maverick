"""Structured target policy helpers for secret grants."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from urllib.parse import urlsplit

from core.secrets.errors import SecretBindingError


MAX_AUDIT_TARGET_LENGTH = 240
MAX_AUDIT_CONTEXT_VALUE_LENGTH = 160
AUDIT_REQUEST_CONTEXT_KEYS = {"surface", "method", "route_path", "tool_name", "command_id"}
SUPPORTED_URL_SCHEMES = {"http", "https", "maverick"}


@dataclass(frozen=True)
class SecretTarget:
    """Normalized URL target without query or fragment material."""

    scheme: str
    host: str
    path: str

    def as_pattern(self) -> str:
        return f"{self.scheme}://{self.host}{self.path}"


def normalize_target_pattern(pattern: str) -> str:
    """Normalize one grant target pattern and reject ambiguous broadening."""
    candidate = str(pattern).strip()
    if candidate == "*":
        return candidate
    parts = urlsplit(candidate)
    if parts.query or parts.fragment:
        raise SecretBindingError("Secret grant target patterns must not include query strings or fragments.")
    target = _parse_url_target(candidate, label="Secret grant target patterns")
    if "*" in target.host and not target.host.startswith("*."):
        raise SecretBindingError("Secret grant host wildcards must use a leading `*.` prefix.")
    if target.host == "*":
        raise SecretBindingError("Secret grant target patterns must not wildcard every host.")
    return target.as_pattern()


def normalize_target_patterns(patterns: list[str] | None) -> list[str]:
    """Normalize a list of target patterns, preserving order and uniqueness."""
    normalized: list[str] = []
    for pattern in patterns or []:
        candidate = str(pattern).strip()
        if not candidate:
            continue
        target = normalize_target_pattern(candidate)
        if target not in normalized:
            normalized.append(target)
    return normalized


def normalize_target_patterns_or_wildcard(patterns: list[str] | None) -> list[str]:
    """Normalize target patterns, using wildcard only where callers deliberately allow it."""
    return normalize_target_patterns(patterns) or ["*"]


def has_explicit_target_patterns(patterns: list[str] | None) -> bool:
    """Return whether the caller supplied at least one non-empty target pattern."""
    return any(str(pattern).strip() for pattern in patterns or [])


def target_allowed(target: str, patterns: list[str]) -> bool:
    """Return whether a runtime target is allowed by normalized grant patterns."""
    if not target:
        return "*" in patterns
    parsed = _parse_url_target(target, label="Secret use targets")
    for pattern in patterns:
        if pattern == "*":
            return True
        parsed_pattern = _parse_url_target(pattern, label="Secret grant target patterns")
        if parsed.scheme != parsed_pattern.scheme:
            continue
        if not _host_allowed(parsed.host, parsed_pattern.host):
            continue
        if fnmatchcase(parsed.path, parsed_pattern.path):
            return True
    return False


def assert_target_patterns_safe_for_actions(actions: list[str], patterns: list[str]) -> None:
    """Reject target declarations that make mixed-action grants globally broad."""
    if len(set(actions)) > 1 and "*" in patterns:
        raise SecretBindingError("Secret grants with multiple actions must use explicit target patterns instead of `*`.")


def sanitize_target_for_audit(target: str | None) -> str | None:
    """Return a query-free, bounded target value suitable for audit payloads."""
    if target is None:
        return None
    candidate = str(target).strip()
    if not candidate:
        return None
    try:
        parsed = _parse_url_target(candidate, label="Secret use targets")
        sanitized = parsed.as_pattern()
    except SecretBindingError:
        sanitized = candidate.split("?", 1)[0].split("#", 1)[0]
    if len(sanitized) <= MAX_AUDIT_TARGET_LENGTH:
        return sanitized
    return f"{sanitized[:MAX_AUDIT_TARGET_LENGTH]}..."


def sanitize_request_context_for_audit(context: dict[str, str] | None) -> dict[str, str]:
    """Return allowlisted, bounded request context metadata for audit payloads."""
    if not isinstance(context, dict):
        return {}
    sanitized: dict[str, str] = {}
    for key in sorted(AUDIT_REQUEST_CONTEXT_KEYS):
        if key not in context:
            continue
        raw_value = context.get(key)
        if raw_value is None:
            continue
        value = str(raw_value).strip()
        if not value:
            continue
        if len(value) > MAX_AUDIT_CONTEXT_VALUE_LENGTH:
            value = f"{value[:MAX_AUDIT_CONTEXT_VALUE_LENGTH]}..."
        sanitized[key] = value
    return sanitized


def _parse_url_target(value: str, *, label: str) -> SecretTarget:
    parts = urlsplit(value)
    scheme = parts.scheme.lower()
    if scheme not in SUPPORTED_URL_SCHEMES:
        raise SecretBindingError(f"{label} must use http, https, or maverick URLs.")
    if not parts.hostname:
        raise SecretBindingError(f"{label} must include a hostname.")
    if parts.username or parts.password:
        raise SecretBindingError(f"{label} must not include URL credentials.")
    path = parts.path or "/"
    host = _normalize_host(parts.hostname)
    if parts.port is not None:
        host = f"{host}:{parts.port}"
    if not path.startswith("/"):
        path = f"/{path}"
    return SecretTarget(scheme=scheme, host=host, path=path)


def _normalize_host(host: str) -> str:
    if host.startswith("*."):
        return f"*.{host[2:].encode('idna').decode('ascii').lower()}"
    return host.encode("idna").decode("ascii").lower()


def _host_allowed(target_host: str, pattern_host: str) -> bool:
    if pattern_host.startswith("*."):
        suffix = pattern_host[1:]
        return target_host.endswith(suffix) and target_host != pattern_host[2:]
    return target_host == pattern_host
