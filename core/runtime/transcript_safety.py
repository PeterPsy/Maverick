"""Redaction and allowlisting for user-visible transcript fields."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
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
_CAMEL_CASE_BOUNDARY = re.compile(r"([a-z0-9])([A-Z])")
_NON_KEY_CHARACTER = re.compile(r"[^a-z0-9]+")
_FORBIDDEN_STRUCTURED_KEY_TOKENS = frozenset(
    _NON_KEY_CHARACTER.sub("", key) for key in _FORBIDDEN_STRUCTURED_KEYS
)
_MAX_STRUCTURED_DEPTH = 6
_MAX_STRUCTURED_ITEMS = 100
_MAX_STRUCTURED_KEY_CHARS = 240
_MAX_STRUCTURED_STRING_CHARS = 4_000
_MAX_STRUCTURED_NODES = 200
_MAX_STRUCTURED_PAYLOAD_BYTES = 13_500
MAX_STRUCTURED_CONTENT_SERIALIZED_BYTES = 16_384
_OMITTED = object()


@dataclass
class _StructuredBudget:
    remaining_nodes: int = _MAX_STRUCTURED_NODES
    remaining_bytes: int = _MAX_STRUCTURED_PAYLOAD_BYTES
    truncated: bool = False
    redactions_applied: bool = False

    def consume_node(self) -> bool:
        if self.remaining_nodes <= 0:
            self.truncated = True
            return False
        self.remaining_nodes -= 1
        return True

    def consume_bytes(self, count: int) -> bool:
        if count > self.remaining_bytes:
            self.truncated = True
            return False
        self.remaining_bytes -= count
        return True


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


def safe_structured_content(value: object) -> tuple[dict[str, Any] | None, bool, bool]:
    """Project a visible structured envelope without technical runtime fields."""
    if not isinstance(value, Mapping):
        return None, False, False
    kind = str(value.get("kind") or "").strip()
    if not kind:
        return None, False, False
    budget = _StructuredBudget()
    redacted_kind = redact_transcript_text(kind)
    if redacted_kind != kind:
        budget.redactions_applied = True
    safe_kind = redacted_kind[:160]
    if len(safe_kind) != len(redacted_kind):
        budget.truncated = True
    payload_source = value.get("payload") if isinstance(value.get("payload"), Mapping) else value
    payload = _safe_structured_value(payload_source, budget=budget, depth=0)
    if not isinstance(payload, dict):
        payload = {}
        budget.truncated = True
    payload.pop("kind", None)
    result = {"kind": safe_kind, "payload": payload}
    if _serialized_size(result) > MAX_STRUCTURED_CONTENT_SERIALIZED_BYTES:
        result = {"kind": safe_kind, "payload": {}}
        budget.truncated = True
    redactions_applied = budget.redactions_applied or budget.truncated
    return result, redactions_applied, budget.truncated


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
            if len(key_text) > _MAX_STRUCTURED_KEY_CHARS:
                redacted = True
                continue
            normalized_key = _canonical_structured_key(key_text)
            if _structured_key_is_forbidden(normalized_key):
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


def _safe_structured_value(value: object, *, budget: _StructuredBudget, depth: int):
    if depth >= _MAX_STRUCTURED_DEPTH or not budget.consume_node():
        budget.truncated = True
        return _OMITTED
    if isinstance(value, Mapping):
        if not budget.consume_bytes(2):
            return _OMITTED
        result: dict[str, Any] = {}
        for index, (key, child) in enumerate(value.items()):
            if index >= _MAX_STRUCTURED_ITEMS:
                budget.truncated = True
                break
            key_text = str(key)
            if len(key_text) > _MAX_STRUCTURED_KEY_CHARS:
                budget.truncated = True
                continue
            normalized_key = _canonical_structured_key(key_text)
            if _structured_key_is_forbidden(normalized_key):
                budget.redactions_applied = True
                continue
            key_cost = _serialized_size(key_text) + 1 + (1 if result else 0)
            if not budget.consume_bytes(key_cost):
                break
            if is_sensitive_key(normalized_key):
                budget.redactions_applied = True
                child = REDACTED
            safe_child = _safe_structured_value(child, budget=budget, depth=depth + 1)
            if safe_child is _OMITTED:
                break
            result[key_text] = safe_child
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if not budget.consume_bytes(2):
            return _OMITTED
        result = []
        for index, child in enumerate(value):
            if index >= _MAX_STRUCTURED_ITEMS:
                budget.truncated = True
                break
            if result and not budget.consume_bytes(1):
                break
            safe_child = _safe_structured_value(child, budget=budget, depth=depth + 1)
            if safe_child is _OMITTED:
                break
            result.append(safe_child)
        return result
    if isinstance(value, str):
        safe_text = redact_transcript_text(value)
        if safe_text != value:
            budget.redactions_applied = True
        if len(safe_text) > _MAX_STRUCTURED_STRING_CHARS:
            safe_text = safe_text[:_MAX_STRUCTURED_STRING_CHARS]
            budget.truncated = True
        return _fit_string_to_budget(safe_text, budget)
    if value is None or isinstance(value, (bool, int, float)):
        if not budget.consume_bytes(_serialized_size(value)):
            return _OMITTED
        return value
    budget.redactions_applied = True
    return _fit_string_to_budget(str(value)[:500], budget)


def _fit_string_to_budget(value: str, budget: _StructuredBudget):
    encoded_size = _serialized_size(value)
    if budget.consume_bytes(encoded_size):
        return value
    low = 0
    high = len(value)
    while low < high:
        midpoint = (low + high + 1) // 2
        if _serialized_size(value[:midpoint]) <= budget.remaining_bytes:
            low = midpoint
        else:
            high = midpoint - 1
    if low == 0 and _serialized_size("") > budget.remaining_bytes:
        return _OMITTED
    fitted = value[:low]
    budget.consume_bytes(_serialized_size(fitted))
    budget.truncated = True
    return fitted


def _canonical_structured_key(value: str) -> str:
    separated = _CAMEL_CASE_BOUNDARY.sub(r"\1_\2", value.strip()).replace("-", "_")
    return re.sub(r"_+", "_", separated).strip("_").lower()


def _structured_key_is_forbidden(normalized_key: str) -> bool:
    collapsed = _NON_KEY_CHARACTER.sub("", normalized_key)
    return (
        normalized_key in _FORBIDDEN_STRUCTURED_KEYS
        or collapsed in _FORBIDDEN_STRUCTURED_KEY_TOKENS
        or normalized_key == "raw"
        or normalized_key.startswith("raw_")
    )


def _serialized_size(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("utf-8"))
