"""Public service for compacting runtime.tool_call event payloads."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from core.runtime.execution_events import RuntimeExecutionEvent
from core.runtime.output_compaction.classifier import classify_tool_output
from core.runtime.output_compaction.event_payloads import (
    COMPACTION_SCOPE,
    DESCRIPTIVE_TEXT_FIELDS,
    DESCRIPTIVE_TEXT_SEQUENCE_FIELDS,
    OUTPUT_FIELDS,
    apply_result,
    input_from_event,
    redact_descriptive_payload_fields,
    result_is_noop,
)
from core.runtime.output_compaction.fallbacks import compactor_error_result
from core.runtime.output_compaction.models import (
    ToolOutputCompactionContext,
    ToolOutputCompactionInput,
    ToolOutputCompactionPolicy,
    ToolOutputCompactionResult,
)
from core.runtime.output_compaction.raw_payload import collect_raw_text_fields, sanitize_raw_payload
from core.runtime.output_compaction.redaction import redact_text
from core.runtime.output_compaction.reducers import reduce_tool_output
from core.runtime.output_compaction.results import (
    build_compacted_text,
    is_failure,
    pass_through_result,
    redacted_digest,
    redaction_failure_result,
    unchanged_result,
)
from core.runtime.output_compaction.text import byte_len


def compact_tool_call_event(
    event: RuntimeExecutionEvent,
    *,
    context: ToolOutputCompactionContext | None = None,
    policy: ToolOutputCompactionPolicy | None = None,
) -> RuntimeExecutionEvent:
    """Compact persisted runtime.tool_call payloads before storage and live fanout."""
    active_policy = policy or ToolOutputCompactionPolicy.from_environment()
    if not active_policy.enabled or not event.event_type.startswith("runtime.tool_call."):
        return event
    existing_metadata = event.payload.get("output_compaction")
    if _already_trusted_compacted_payload(event.payload, existing_metadata, policy=active_policy):
        return event
    context = context or ToolOutputCompactionContext()
    payload = dict(event.payload)
    redacted_descriptor_fields = redact_descriptive_payload_fields(payload)
    try:
        compaction_input = input_from_event(event, payload=payload, context=context)
    except Exception:
        if redacted_descriptor_fields:
            return replace(event, payload=payload)
        return event
    try:
        result = compact_tool_output(compaction_input, policy=active_policy)
    except Exception as error:
        result = compactor_error_result(compaction_input, policy=active_policy, error=error)
    if redacted_descriptor_fields:
        result = replace(
            result,
            fields=tuple(dict.fromkeys([*result.fields, *redacted_descriptor_fields])),
            redacted=True,
        )
    if result_is_noop(result, payload) and not redacted_descriptor_fields:
        return event
    apply_result(payload, result)
    return replace(event, payload=payload)


def _already_trusted_compacted_payload(
    payload: Mapping[str, object],
    metadata: object,
    *,
    policy: ToolOutputCompactionPolicy,
) -> bool:
    if not isinstance(metadata, Mapping) or metadata.get("scope") != COMPACTION_SCOPE:
        return False
    max_allowed_bytes = max(policy.target_max_compacted_bytes, policy.failure_target_max_compacted_bytes)
    for key in OUTPUT_FIELDS:
        value = payload.get(key)
        if not isinstance(value, str):
            continue
        if byte_len(value) > max_allowed_bytes or redact_text(value) != value:
            return False
    raw = payload.get("raw")
    if isinstance(raw, Mapping) and collect_raw_text_fields(raw):
        return False
    for key in DESCRIPTIVE_TEXT_FIELDS:
        value = payload.get(key)
        if isinstance(value, str) and redact_text(value) != value:
            return False
    for key in DESCRIPTIVE_TEXT_SEQUENCE_FIELDS:
        value = payload.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, str) and redact_text(item) != item:
                return False
    return True


def compact_tool_output(
    compaction_input: ToolOutputCompactionInput,
    *,
    policy: ToolOutputCompactionPolicy,
) -> ToolOutputCompactionResult:
    """Compact one normalized tool output payload."""
    string_fields = _string_fields(compaction_input)
    raw_text_fields = collect_raw_text_fields(compaction_input.raw)
    field_names = tuple([*string_fields.keys(), *(path for path, _value in raw_text_fields)])
    original_bytes = sum(byte_len(value) for value in string_fields.values()) + sum(byte_len(value) for _path, value in raw_text_fields)
    sanitized_raw_result = sanitize_raw_payload(compaction_input.raw) if policy.sanitize_raw_payload else None
    sanitized_raw = sanitized_raw_result.raw if sanitized_raw_result is not None else compaction_input.raw
    raw_omitted_fields = sanitized_raw_result.omitted_fields if sanitized_raw_result is not None else ()

    if original_bytes == 0 and not raw_omitted_fields:
        return unchanged_result(
            compaction_input,
            raw=sanitized_raw,
            policy=policy,
            redacted=bool(sanitized_raw_result and sanitized_raw_result.redacted),
        )

    try:
        redacted_fields = {key: redact_text(value) for key, value in string_fields.items()}
        redacted_raw_fields = tuple((path, redact_text(value)) for path, value in raw_text_fields)
    except Exception:
        return redaction_failure_result(
            compaction_input,
            raw=sanitized_raw,
            original_bytes=original_bytes,
            fields=tuple([*field_names, *raw_omitted_fields]),
            policy=policy,
        )

    redacted_bytes = sum(byte_len(value) for value in redacted_fields.values()) + sum(byte_len(value) for _path, value in redacted_raw_fields)
    combined_text = _combined_text(redacted_fields, redacted_raw_fields)
    digest = redacted_digest(combined_text)
    failed = is_failure(compaction_input)
    required_savings_ratio = policy.failure_min_savings_ratio if failed else policy.success_min_savings_ratio
    target_max_compacted_bytes = policy.failure_target_max_compacted_bytes if failed else policy.target_max_compacted_bytes
    all_fields = tuple(dict.fromkeys([*field_names, *raw_omitted_fields]))

    if original_bytes < policy.min_original_bytes:
        return pass_through_result(
            compaction_input,
            raw=sanitized_raw,
            redacted_fields=redacted_fields,
            redacted_raw_fields=redacted_raw_fields,
            applied=False,
            pass_through_reason="below_min_original_bytes",
            rule_id=None,
            family=None,
            original_bytes=original_bytes,
            redacted_bytes=redacted_bytes,
            required_savings_ratio=required_savings_ratio,
            target_max_compacted_bytes=target_max_compacted_bytes,
            digest=digest,
            fields=all_fields,
            facts={},
        )

    selection = classify_tool_output(compaction_input, combined_text)
    try:
        reduced = reduce_tool_output(selection, compaction_input, combined_text, policy=policy, failed=failed)
    except Exception as error:
        return pass_through_result(
            compaction_input,
            raw=sanitized_raw,
            redacted_fields=redacted_fields,
            redacted_raw_fields=redacted_raw_fields,
            applied=False,
            pass_through_reason="reducer_failed",
            rule_id=selection.rule_id,
            family=selection.family,
            original_bytes=original_bytes,
            redacted_bytes=redacted_bytes,
            required_savings_ratio=required_savings_ratio,
            target_max_compacted_bytes=target_max_compacted_bytes,
            digest=digest,
            fields=all_fields,
            facts={},
            compaction_error=error.__class__.__name__,
        )

    compacted_text, compacted_bytes, actual_savings_ratio = build_compacted_text(
        selection=selection,
        compaction_input=compaction_input,
        reduced_text=reduced.text,
        facts=reduced.facts,
        original_bytes=original_bytes,
        redacted_bytes=redacted_bytes,
        target_max_compacted_bytes=target_max_compacted_bytes,
        digest=digest,
    )

    if actual_savings_ratio < required_savings_ratio:
        return pass_through_result(
            compaction_input,
            raw=sanitized_raw,
            redacted_fields=redacted_fields,
            redacted_raw_fields=redacted_raw_fields,
            applied=False,
            pass_through_reason="insufficient_savings_failure" if failed else "insufficient_savings_success",
            rule_id=selection.rule_id,
            family=selection.family,
            original_bytes=original_bytes,
            redacted_bytes=redacted_bytes,
            required_savings_ratio=required_savings_ratio,
            target_max_compacted_bytes=target_max_compacted_bytes,
            digest=digest,
            fields=all_fields,
            facts=reduced.facts,
        )

    stdout_omitted = compaction_input.stdout is not None
    stderr_omitted = compaction_input.stderr is not None
    return ToolOutputCompactionResult(
        output=compacted_text,
        stdout="" if stdout_omitted else compaction_input.stdout,
        stderr="" if stderr_omitted else compaction_input.stderr,
        raw=sanitized_raw,
        applied=True,
        pass_through_reason="",
        rule_id=selection.rule_id,
        family=selection.family,
        original_bytes=original_bytes,
        redacted_bytes=redacted_bytes,
        compacted_bytes=compacted_bytes,
        savings_ratio=actual_savings_ratio,
        required_savings_ratio=required_savings_ratio,
        target_max_compacted_bytes=target_max_compacted_bytes,
        redacted=True,
        redacted_sha256=digest,
        fields=all_fields,
        facts=reduced.facts,
        stdout_omitted=stdout_omitted,
        stderr_omitted=stderr_omitted,
    )


def _string_fields(compaction_input: ToolOutputCompactionInput) -> dict[str, str]:
    fields: dict[str, str] = {}
    for key in OUTPUT_FIELDS:
        value = getattr(compaction_input, key)
        if isinstance(value, str):
            fields[key] = value
    return fields


def _combined_text(fields: Mapping[str, str], raw_fields: tuple[tuple[str, str], ...]) -> str:
    parts: list[tuple[str, str]] = []
    seen_values: set[str] = set()
    for key, value in fields.items():
        if not value:
            continue
        parts.append((key, value))
        seen_values.add(value)
    for path, value in raw_fields:
        if not value or value in seen_values:
            continue
        parts.append((path, value))
        seen_values.add(value)
    if len(parts) == 1:
        return parts[0][1]
    return "\n\n".join(f"### {label}\n{value}" for label, value in parts)
