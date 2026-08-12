"""Redaction and allowlisting for user-visible transcript fields."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any

from core.runtime.output_compaction.redaction import REDACTED, is_sensitive_key, redact_text


_FORBIDDEN_STRUCTURED_KEYS = {
    "developer_prompt",
    "environment",
    "env",
    "local_path",
    "provider_payload",
    "provider_thread_id",
    "raw",
    "runtime_root",
    "system_prompt",
    "workdir",
    "workspace_root",
}
_RUNTIME_PATH_PATTERN = re.compile(r"(?:^|[\s(])/(?:[^\s)]+/)*runtime/sessions/[^\s)]+")
_MAX_STRUCTURED_DEPTH = 6
_MAX_STRUCTURED_ITEMS = 100
_MAX_STRUCTURED_STRING_CHARS = 4_000


def safe_attachment_items(value: object) -> tuple[list[dict[str, Any]], bool]:
    """Return only attachment fields intentionally visible in Chat."""
    if not isinstance(value, list):
        return [], False
    allowed = {
        "id",
        "file_id",
        "name",
        "filename",
        "mime_type",
        "size_bytes",
        "workspace_relative_path",
        "relative_path",
        "role",
    }
    items: list[dict[str, Any]] = []
    redacted = False
    for candidate in value[:5]:
        if not isinstance(candidate, Mapping):
            continue
        item: dict[str, Any] = {}
        for key, child in candidate.items():
            key_text = str(key)
            if key_text not in allowed:
                redacted = True
                continue
            safe_child, child_redacted = safe_visible_value(child)
            item[key_text] = safe_child
            redacted = redacted or child_redacted
        if item:
            items.append(item)
    return items, redacted or len(value) > 5


def safe_app_reference_items(value: object) -> tuple[list[dict[str, Any]], bool]:
    """Return the stable, user-visible subset of app references."""
    if not isinstance(value, list):
        return [], False
    allowed = {"type", "app_id", "entity_type", "entity_id", "label", "summary", "deep_link", "exists"}
    items: list[dict[str, Any]] = []
    redacted = False
    for candidate in value[:50]:
        if not isinstance(candidate, Mapping):
            continue
        item: dict[str, Any] = {}
        for key, child in candidate.items():
            key_text = str(key)
            if key_text not in allowed:
                redacted = True
                continue
            safe_child, child_redacted = safe_visible_value(child)
            item[key_text] = safe_child
            redacted = redacted or child_redacted
        if item:
            items.append(item)
    return items, redacted or len(value) > 50


def safe_structured_content(value: object) -> tuple[dict[str, Any] | None, bool]:
    """Project a visible structured envelope without technical runtime fields."""
    if not isinstance(value, Mapping):
        return None, False
    kind = str(value.get("kind") or "").strip()
    if not kind:
        return None, False
    payload_source = value.get("payload") if isinstance(value.get("payload"), Mapping) else value
    payload, redacted = safe_visible_value(payload_source)
    if not isinstance(payload, dict):
        payload = {}
        redacted = True
    payload.pop("kind", None)
    return {"kind": kind[:160], "payload": payload}, redacted or len(kind) > 160


def safe_visible_value(value: object, *, depth: int = 0) -> tuple[Any, bool]:
    """Recursively bound and redact a user-visible structured value."""
    if depth >= _MAX_STRUCTURED_DEPTH:
        return "<redacted: structured value too deep>", True
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        redacted = False
        for index, (key, child) in enumerate(value.items()):
            if index >= _MAX_STRUCTURED_ITEMS:
                redacted = True
                break
            key_text = str(key)
            normalized_key = key_text.strip().lower().replace("-", "_")
            if normalized_key in _FORBIDDEN_STRUCTURED_KEYS or normalized_key.startswith("raw_"):
                redacted = True
                continue
            if is_sensitive_key(normalized_key):
                result[key_text] = REDACTED
                redacted = True
                continue
            safe_child, child_redacted = safe_visible_value(child, depth=depth + 1)
            result[key_text] = safe_child
            redacted = redacted or child_redacted
        return result, redacted
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        items = []
        redacted = len(value) > _MAX_STRUCTURED_ITEMS
        for child in value[:_MAX_STRUCTURED_ITEMS]:
            safe_child, child_redacted = safe_visible_value(child, depth=depth + 1)
            items.append(safe_child)
            redacted = redacted or child_redacted
        return items, redacted
    if isinstance(value, str):
        safe_text = redact_transcript_text(value)
        redacted = safe_text != value
        if len(safe_text) > _MAX_STRUCTURED_STRING_CHARS:
            safe_text = safe_text[:_MAX_STRUCTURED_STRING_CHARS] + "\n<redacted: oversized structured field>"
            redacted = True
        return safe_text, redacted
    if value is None or isinstance(value, (bool, int, float)):
        return value, False
    return str(value)[:500], True


def redact_transcript_text(value: str) -> str:
    """Redact common secrets and runtime-session filesystem locations."""
    redacted = redact_text(str(value))
    return _RUNTIME_PATH_PATTERN.sub(" <redacted-runtime-path>", redacted)
