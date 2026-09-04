"""Validation policy for parent-bound nested widget launches."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlsplit

from core.api.app_frame_launch import clean_relative_origin_url
from core.api.session_api import RequestSession
from core.api.widget_context import verify_widget_context
from core.apps.errors import AppHostingError


def clean_nested_widget_launch_path(
    value: object,
    *,
    owner_app_id: str,
    widget_id: str,
    context_token: str,
) -> str:
    """Require the exact requested widget mount and append opaque context."""
    raw = clean_relative_origin_url(value)
    parsed = urlsplit(raw)
    expected_prefix = f"/api/apps/widgets/{owner_app_id}/{widget_id}/frontend/"
    if parsed.fragment or not parsed.path.startswith(expected_prefix):
        raise AppHostingError("Widget frame launch path does not match the requested widget.")
    return f"{raw}#context={quote(context_token, safe='')}"


def verify_nested_widget_context(token: str) -> dict[str, Any] | None:
    """Fail closed for malformed or incorrectly signed widget context."""
    try:
        return verify_widget_context(token)
    except (ValueError, TypeError, UnicodeError):
        return None


def nested_widget_context_matches(
    payload: dict[str, Any] | None,
    *,
    context: RequestSession,
    owner_app_id: str,
    widget_id: str,
    widget_host: str,
    content_kinds: list[str],
) -> bool:
    """Match every context field that controls a nested widget surface."""
    if payload is None:
        return False
    content = payload.get("content")
    content_kind = content.get("kind") if isinstance(content, dict) else None
    return (
        payload.get("workspace_id") == context.workspace_id
        and payload.get("user_id") == context.user.user_id
        and payload.get("host_app_id") == widget_host
        and payload.get("owner_app_id") == owner_app_id
        and payload.get("widget_id") == widget_id
        and content_kind in content_kinds
    )


def bounded_request_string(value: object, *, maximum: int) -> str:
    """Return a trimmed bounded scalar string or an empty invalid marker."""
    if not isinstance(value, str):
        return ""
    candidate = value.strip()
    if not candidate or len(candidate) > maximum or any(ord(character) < 32 for character in candidate):
        return ""
    return candidate
