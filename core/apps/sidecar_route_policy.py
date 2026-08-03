"""Exact, segment-aware matching for governed HTTP sidecar routes."""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import unquote_to_bytes

from core.apps.models import HttpSidecarRoutePolicy, HttpSidecarRouteRule


_PARAMETER_SEGMENT = re.compile(r"^\{[A-Za-z][A-Za-z0-9_]*\}$")
_LITERAL_SEGMENT = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._~-]*$")
_PERCENT_ESCAPE = re.compile(br"%[0-9A-Fa-f]{2}")
_FORBIDDEN_RAW_ESCAPES = (b"%2f", b"%5c", b"%25", b"%2e")


def validate_route_template(value: str, *, static_tree: bool) -> str:
    """Validate a declarative template without accepting app-provided regex."""
    if not value.startswith("/") or value != (value.rstrip("/") or "/"):
        raise ValueError("must be a canonical absolute path without a trailing slash")
    if any(character in value for character in ("\\", "?", "#", "%")):
        raise ValueError("must not contain escaping, query, fragment, or percent encoding")
    if any(ord(character) < 32 for character in value) or "//" in value:
        raise ValueError("must not contain control characters or empty path segments")
    segments = value.split("/")[1:]
    if any(segment in {".", ".."} for segment in segments):
        raise ValueError("must not contain traversal segments")
    parameters: set[str] = set()
    for segment in segments:
        if not segment:
            continue
        if segment.startswith("{") or segment.endswith("}"):
            if not _PARAMETER_SEGMENT.fullmatch(segment):
                raise ValueError("dynamic parameters must be named and consume exactly one segment")
            if segment in parameters:
                raise ValueError("dynamic parameter names must be unique within a template")
            parameters.add(segment)
        elif "{" in segment or "}" in segment:
            raise ValueError("dynamic parameters must occupy a complete path segment")
        elif _LITERAL_SEGMENT.fullmatch(segment) is None:
            raise ValueError("literal segments must not contain regex or routing syntax")
    if static_tree:
        if parameters:
            raise ValueError("static trees cannot contain dynamic parameters")
        if value == "/" or value == "/api" or value.startswith("/api/"):
            raise ValueError("static trees must be rooted outside the sidecar API namespace")
    return value


def canonicalize_sidecar_path(subpath: str) -> str:
    """Canonicalize one already-decoded sidecar subpath exactly once."""
    text = str(subpath or "")
    if text.startswith("//"):
        raise ValueError("ambiguous leading slash")
    text = text.removeprefix("/")
    path = f"/{text}" if text else "/"
    if "%" in path or "\\" in path or "//" in path:
        raise ValueError("encoded, backslash, or empty path segments are forbidden")
    if any(ord(character) < 32 for character in path):
        raise ValueError("control characters are forbidden")
    if unicodedata.normalize("NFC", path) != path:
        raise ValueError("path must already be Unicode NFC")
    if any(segment in {".", ".."} for segment in path.split("/")):
        raise ValueError("traversal segments are forbidden")
    return path.rstrip("/") or "/"


def validate_asgi_raw_path(*, path: object, raw_path: object) -> None:
    """Reject ambiguous percent encoding before decoded ASGI routing proceeds."""
    if raw_path is None:
        canonicalize_sidecar_path(str(path or "/"))
        return
    raw = bytes(raw_path)
    cursor = 0
    while cursor < len(raw):
        if raw[cursor : cursor + 1] != b"%":
            cursor += 1
            continue
        if not _PERCENT_ESCAPE.fullmatch(raw[cursor : cursor + 3]):
            raise ValueError("invalid percent escape")
        cursor += 3
    lowered = raw.lower()
    if any(escape in lowered for escape in _FORBIDDEN_RAW_ESCAPES):
        raise ValueError("encoded slash, traversal, backslash, or double encoding is forbidden")
    try:
        decoded = unquote_to_bytes(raw).decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("raw path must decode as UTF-8") from error
    if decoded != str(path or "/"):
        raise ValueError("raw and decoded ASGI paths disagree")
    canonicalize_sidecar_path(decoded)


def route_policy_mode(policy: HttpSidecarRoutePolicy, *, method: str, path: str) -> str:
    """Return the highest-precedence policy mode for one canonical path."""
    if _matches_any(policy.blocked, method=method, path=path):
        return "blocked"
    if _matches_any(policy.handled_by_core, method=method, path=path):
        return "handled_by_core"
    if _matches_any(policy.pass_through, method=method, path=path):
        return "pass_through"
    return "not_allowed"


def route_rule_matches(rule: HttpSidecarRouteRule, *, method: str, path: str) -> bool:
    """Match exact literal/one-segment templates, or an explicit safe static tree."""
    if rule.method is not None and rule.method != method and not (method == "HEAD" and rule.method == "GET"):
        return False
    if rule.static_tree:
        return path == rule.path_template or path.startswith(f"{rule.path_template}/")
    template_segments = rule.path_template.split("/")[1:]
    path_segments = path.split("/")[1:]
    if len(template_segments) != len(path_segments):
        return False
    return all(
        _PARAMETER_SEGMENT.fullmatch(template) is not None or template == actual
        for template, actual in zip(template_segments, path_segments)
    )


def _matches_any(rules: list[HttpSidecarRouteRule], *, method: str, path: str) -> bool:
    return any(route_rule_matches(rule, method=method, path=path) for rule in rules)
