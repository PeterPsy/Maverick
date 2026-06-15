"""Fail-safe result builders for runtime output compaction errors."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.runtime.output_compaction.event_payloads import OUTPUT_FIELDS
from core.runtime.output_compaction.models import (
    ToolOutputCompactionInput,
    ToolOutputCompactionPolicy,
    ToolOutputCompactionResult,
)
from core.runtime.output_compaction.raw_payload import collect_raw_text_fields, sanitize_raw_payload
from core.runtime.output_compaction.redaction import redact_text
from core.runtime.output_compaction.results import (
    exit_code_fact,
    is_failure,
    pass_through_result,
    redacted_digest,
    redaction_failure_result,
)
from core.runtime.output_compaction.text import byte_len


def compactor_error_result(
    compaction_input: ToolOutputCompactionInput,
    *,
    policy: ToolOutputCompactionPolicy,
    error: Exception,
) -> ToolOutputCompactionResult:
    """Return a redacted event result when the main compactor fails unexpectedly."""
    string_fields = _string_fields(compaction_input)
    raw_text_fields = _safe_collect_raw_text_fields(compaction_input.raw)
    field_names = tuple([*string_fields.keys(), *(path for path, _value in raw_text_fields)])
    original_bytes = sum(byte_len(value) for value in string_fields.values()) + sum(
        byte_len(value) for _path, value in raw_text_fields
    )
    sanitized_raw, raw_omitted_fields = _safe_sanitized_raw(compaction_input.raw, policy=policy)
    all_fields = tuple(dict.fromkeys([*field_names, *raw_omitted_fields]))

    try:
        redacted_fields = {key: redact_text(value) for key, value in string_fields.items()}
        redacted_raw_fields = tuple((path, redact_text(value)) for path, value in raw_text_fields)
    except Exception:
        return redaction_failure_result(
            compaction_input,
            raw=sanitized_raw,
            original_bytes=original_bytes,
            fields=all_fields,
            policy=policy,
        )

    redacted_bytes = sum(byte_len(value) for value in redacted_fields.values()) + sum(
        byte_len(value) for _path, value in redacted_raw_fields
    )
    failed = is_failure(compaction_input)
    return pass_through_result(
        compaction_input,
        raw=sanitized_raw,
        redacted_fields=redacted_fields,
        applied=False,
        pass_through_reason="compactor_failed",
        rule_id=None,
        family=None,
        original_bytes=original_bytes,
        redacted_bytes=redacted_bytes,
        required_savings_ratio=policy.failure_min_savings_ratio if failed else policy.success_min_savings_ratio,
        target_max_compacted_bytes=policy.failure_target_max_compacted_bytes if failed else policy.target_max_compacted_bytes,
        digest=redacted_digest(_combined_text(redacted_fields, redacted_raw_fields)),
        fields=all_fields,
        facts=exit_code_fact(compaction_input),
        compaction_error=error.__class__.__name__,
    )


def _string_fields(compaction_input: ToolOutputCompactionInput) -> dict[str, str]:
    fields: dict[str, str] = {}
    for key in OUTPUT_FIELDS:
        value = getattr(compaction_input, key)
        if isinstance(value, str):
            fields[key] = value
    return fields


def _combined_text(fields: Mapping[str, str], raw_fields: tuple[tuple[str, str], ...]) -> str:
    parts = [value for value in fields.values() if value]
    seen_values = set(parts)
    for _path, value in raw_fields:
        if value and value not in seen_values:
            parts.append(value)
            seen_values.add(value)
    return "\n\n".join(parts)


def _safe_collect_raw_text_fields(raw: Mapping[str, Any] | None) -> tuple[tuple[str, str], ...]:
    try:
        return collect_raw_text_fields(raw)
    except Exception:
        return ()


def _safe_sanitized_raw(
    raw: Mapping[str, Any] | None,
    *,
    policy: ToolOutputCompactionPolicy,
) -> tuple[Mapping[str, Any] | None, tuple[str, ...]]:
    if not policy.sanitize_raw_payload:
        return raw, ()
    try:
        result = sanitize_raw_payload(raw)
    except Exception:
        if raw is None:
            return None, ()
        return {"has_omitted_provider_payload": True, "raw_sanitization_failed": True}, ("raw",)
    return result.raw, result.omitted_fields
