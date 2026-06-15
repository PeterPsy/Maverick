"""Bound and sanitize provider raw payloads for persisted tool-call events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from core.runtime.output_compaction.redaction import REDACTED, is_sensitive_key, redact_text
from core.runtime.output_compaction.text import byte_len, truncate_bytes


RAW_TEXT_KEYS = {
    "aggregatedoutput",
    "aggregated_output",
    "output",
    "stdout",
    "stderr",
    "text",
    "delta",
    "content",
    "message",
}


@dataclass(frozen=True)
class RawPayloadSanitizationResult:
    """Sanitized raw payload and the omitted string field paths."""

    raw: Mapping[str, Any] | None
    omitted_fields: tuple[str, ...]
    redacted: bool


def collect_raw_text_fields(value: Any, *, threshold_bytes: int = 1024) -> tuple[tuple[str, str], ...]:
    """Collect large or known provider text fields from raw payloads."""
    collected: list[tuple[str, str]] = []

    def visit(item: Any, path: str) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                child_path = f"{path}.{key}" if path else str(key)
                visit(child, child_path)
            return
        if isinstance(item, list):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]")
            return
        if not isinstance(item, str):
            return
        key_name = _path_key(path)
        if key_name in RAW_TEXT_KEYS or byte_len(item) > threshold_bytes:
            collected.append((path, item))

    visit(value, "raw")
    return tuple(collected)


def sanitize_raw_payload(
    raw: Mapping[str, Any] | None,
    *,
    omit_text_threshold_bytes: int = 1024,
    max_string_bytes: int = 512,
    max_list_items: int = 20,
    max_depth: int = 6,
) -> RawPayloadSanitizationResult:
    """Return a redacted, bounded raw payload for runtime.tool_call events."""
    if raw is None:
        return RawPayloadSanitizationResult(raw=None, omitted_fields=(), redacted=False)

    omitted_fields: list[str] = []
    redacted = False

    def sanitize(value: Any, path: str, depth: int) -> Any:
        nonlocal redacted
        if depth > max_depth:
            omitted_fields.append(path)
            return "[omitted: max_depth]"
        if isinstance(value, Mapping):
            sanitized: dict[str, Any] = {}
            for key, item in value.items():
                key_text = str(key)
                child_path = f"{path}.{key_text}" if path else key_text
                if is_sensitive_key(key_text):
                    sanitized[key_text] = REDACTED
                    redacted = True
                    continue
                sanitized_value = sanitize(item, child_path, depth + 1)
                if sanitized_value is _OMITTED:
                    continue
                sanitized[key_text] = sanitized_value
            return sanitized
        if isinstance(value, list):
            result = []
            for index, item in enumerate(value[:max_list_items]):
                sanitized_item = sanitize(item, f"{path}[{index}]", depth + 1)
                if sanitized_item is not _OMITTED and sanitized_item != {}:
                    result.append(sanitized_item)
            if len(value) > max_list_items:
                omitted_fields.append(f"{path}[{max_list_items}:]")
                result.append(f"[omitted {len(value) - max_list_items} list items]")
            return result
        if isinstance(value, str):
            key_name = _path_key(path)
            if key_name in RAW_TEXT_KEYS and byte_len(value) > omit_text_threshold_bytes:
                omitted_fields.append(path)
                return _OMITTED
            redacted_value = redact_text(value)
            if redacted_value != value:
                redacted = True
            if byte_len(redacted_value) > max_string_bytes:
                omitted_fields.append(path)
                return f"{truncate_bytes(redacted_value, max_string_bytes)}\n[omitted provider string]"
            return redacted_value
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    sanitized_raw = sanitize(raw, "raw", 0)
    if not isinstance(sanitized_raw, Mapping):
        return RawPayloadSanitizationResult(raw=None, omitted_fields=tuple(omitted_fields), redacted=redacted)

    if isinstance(raw.get("item"), Mapping):
        item = raw["item"]
        item_type = str(item.get("type") or "").strip()
        if item_type:
            sanitized_raw = dict(sanitized_raw)
            sanitized_raw["item_type"] = item_type
    if omitted_fields:
        sanitized_raw = dict(sanitized_raw)
        sanitized_raw["has_omitted_provider_payload"] = True
        sanitized_raw["omitted_provider_payload_fields"] = tuple(omitted_fields[:20])
    return RawPayloadSanitizationResult(raw=sanitized_raw, omitted_fields=tuple(omitted_fields), redacted=redacted)


class _OmittedSentinel:
    pass


_OMITTED = _OmittedSentinel()


def _path_key(path: str) -> str:
    tail = path.rsplit(".", 1)[-1]
    if "[" in tail:
        tail = tail.split("[", 1)[0]
    return tail.replace("-", "_").replace("_", "").lower()
