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
    redacted_digest,
    redaction_failure_result,
    savings_ratio,
)
from core.runtime.output_compaction.text import byte_len, truncate_middle_bytes


COMPACTOR_FAILURE_MARKER = "[tool output compacted: compactor_failed]"


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
    required_savings_ratio = policy.failure_min_savings_ratio if failed else policy.success_min_savings_ratio
    target_max_compacted_bytes = policy.failure_target_max_compacted_bytes if failed else policy.target_max_compacted_bytes
    combined_text = _combined_text(redacted_fields, redacted_raw_fields)
    digest = redacted_digest(combined_text)
    bounded_fields, stdout_omitted, stderr_omitted = _bounded_compactor_error_fields(
        compaction_input,
        redacted_fields=redacted_fields,
        redacted_raw_fields=redacted_raw_fields,
        original_bytes=original_bytes,
        redacted_bytes=redacted_bytes,
        target_max_compacted_bytes=target_max_compacted_bytes,
        digest=digest,
    )
    compacted_bytes = sum(byte_len(value) for value in bounded_fields.values())
    return ToolOutputCompactionResult(
        output=bounded_fields.get("output", compaction_input.output),
        stdout=bounded_fields.get("stdout", compaction_input.stdout),
        stderr=bounded_fields.get("stderr", compaction_input.stderr),
        raw=sanitized_raw,
        applied=False,
        pass_through_reason="compactor_failed",
        rule_id=None,
        family=None,
        original_bytes=original_bytes,
        redacted_bytes=redacted_bytes,
        compacted_bytes=compacted_bytes,
        savings_ratio=savings_ratio(original_bytes, compacted_bytes),
        required_savings_ratio=required_savings_ratio,
        target_max_compacted_bytes=target_max_compacted_bytes,
        redacted=True,
        redacted_sha256=digest,
        fields=all_fields,
        facts=exit_code_fact(compaction_input),
        stdout_omitted=stdout_omitted,
        stderr_omitted=stderr_omitted,
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


def _bounded_compactor_error_fields(
    compaction_input: ToolOutputCompactionInput,
    *,
    redacted_fields: Mapping[str, str],
    redacted_raw_fields: tuple[tuple[str, str], ...],
    original_bytes: int,
    redacted_bytes: int,
    target_max_compacted_bytes: int,
    digest: str,
) -> tuple[dict[str, str], bool, bool]:
    current_fields = {key: value for key, value in redacted_fields.items()}
    current_bytes = sum(byte_len(value) for value in current_fields.values())
    if current_fields and current_bytes <= target_max_compacted_bytes:
        return current_fields, False, False

    combined_text = _combined_text(redacted_fields, redacted_raw_fields).strip()
    header = "\n".join(
        [
            COMPACTOR_FAILURE_MARKER,
            "scope: fallback",
            "pass_through_reason: compactor_failed",
            f"original_bytes: {original_bytes}",
            f"redacted_bytes: {redacted_bytes}",
            f"target_max_compacted_bytes: {target_max_compacted_bytes}",
            f"redacted_sha256: {digest}",
        ]
    )
    if combined_text:
        body_budget = max(0, target_max_compacted_bytes - byte_len(header) - 2)
        body = truncate_middle_bytes(
            combined_text,
            body_budget,
            marker="\n[... omitted after compactor_failed ...]\n",
        )
        bounded = f"{header}\n\n{body}" if body else header
    else:
        bounded = header
    bounded = truncate_middle_bytes(
        bounded,
        target_max_compacted_bytes,
        marker="\n[... omitted after compactor_failed ...]\n",
    )
    fields = {"output": bounded}
    if compaction_input.stdout is not None:
        fields["stdout"] = ""
    if compaction_input.stderr is not None:
        fields["stderr"] = ""
    return fields, compaction_input.stdout is not None, compaction_input.stderr is not None


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
