"""Runtime event payload adapters for tool-output compaction."""

from __future__ import annotations

from collections.abc import Mapping
import shlex
from typing import Any

from core.runtime.execution_events import RuntimeExecutionEvent
from core.runtime.output_compaction.models import (
    ToolOutputCompactionContext,
    ToolOutputCompactionInput,
    ToolOutputCompactionResult,
)
from core.runtime.output_compaction.redaction import redact_text


OUTPUT_FIELDS = ("output", "stdout", "stderr")
DESCRIPTIVE_TEXT_FIELDS = ("command", "summary", "cwd", "query")
DESCRIPTIVE_TEXT_SEQUENCE_FIELDS = ("argv",)
COMPACTION_VERSION = 1
COMPACTION_SCOPE = "runtime_event_payload"


def input_from_event(
    event: RuntimeExecutionEvent,
    *,
    payload: Mapping[str, Any],
    context: ToolOutputCompactionContext,
) -> ToolOutputCompactionInput:
    """Normalize one runtime event payload into compaction input."""
    command = _optional_string(payload.get("command"))
    raw = payload.get("raw") if isinstance(payload.get("raw"), Mapping) else None
    return ToolOutputCompactionInput(
        provider_id=_optional_string(payload.get("provider_id")),
        provider_event_type=_optional_string(payload.get("provider_event_type")),
        runtime_session_id=context.session_id,
        turn_id=context.turn_id,
        event_type=event.event_type,
        tool_call_id=_optional_string(payload.get("tool_call_id")),
        tool_name=_optional_string(payload.get("name")),
        tool_kind=_optional_string(payload.get("tool_kind")),
        command=command,
        argv=_argv_from_payload(payload, command),
        cwd=_optional_string(payload.get("cwd")),
        output=_optional_string(payload.get("output"), allow_empty=True),
        stdout=_optional_string(payload.get("stdout"), allow_empty=True),
        stderr=_optional_string(payload.get("stderr"), allow_empty=True),
        exit_code=payload.get("exit_code") if isinstance(payload.get("exit_code"), int) else None,
        raw=raw,
        metadata=payload,
    )


def apply_result(payload: dict[str, Any], result: ToolOutputCompactionResult) -> None:
    """Apply compacted fields and metadata to a runtime event payload."""
    for key in OUTPUT_FIELDS:
        value = getattr(result, key)
        if value is not None or key in payload:
            payload[key] = value if value is not None else ""
    if result.raw is not None or "raw" in payload:
        payload["raw"] = dict(result.raw or {})
    payload["output_compaction"] = result_metadata(result)


def redact_descriptive_payload_fields(payload: dict[str, Any]) -> tuple[str, ...]:
    """Redact short descriptive tool-call fields that are persisted outside output."""
    changed: list[str] = []
    for key in DESCRIPTIVE_TEXT_FIELDS:
        value = payload.get(key)
        if not isinstance(value, str):
            continue
        redacted = redact_text(value)
        if redacted != value:
            payload[key] = redacted
            changed.append(key)

    for key in DESCRIPTIVE_TEXT_SEQUENCE_FIELDS:
        value = payload.get(key)
        if not isinstance(value, list):
            continue
        redacted_items: list[Any] = []
        sequence_changed = False
        for item in value:
            if not isinstance(item, str):
                redacted_items.append(item)
                continue
            redacted = redact_text(item)
            if redacted != item:
                sequence_changed = True
            redacted_items.append(redacted)
        if sequence_changed:
            payload[key] = redacted_items
            changed.append(key)
    return tuple(changed)


def result_is_noop(result: ToolOutputCompactionResult, payload: Mapping[str, Any]) -> bool:
    """Return true when compaction did not change an event payload."""
    return (
        result.pass_through_reason == "no_text_fields"
        and result.raw == payload.get("raw")
        and result.output == payload.get("output")
        and result.stdout == payload.get("stdout")
        and result.stderr == payload.get("stderr")
    )


def result_metadata(result: ToolOutputCompactionResult) -> dict[str, Any]:
    """Build the stable payload.output_compaction metadata contract."""
    metadata: dict[str, Any] = {
        "version": COMPACTION_VERSION,
        "scope": COMPACTION_SCOPE,
        "applied": result.applied,
        "rule_id": result.rule_id,
        "family": result.family,
        "original_bytes": result.original_bytes,
        "redacted_bytes": result.redacted_bytes,
        "compacted_bytes": result.compacted_bytes,
        "savings_ratio": round(result.savings_ratio, 6),
        "required_savings_ratio": result.required_savings_ratio,
        "target_max_compacted_bytes": result.target_max_compacted_bytes,
        "redacted": result.redacted,
        "digest_kind": "redacted_sha256",
        "digest": result.redacted_sha256,
        "fields": list(result.fields),
        "pass_through_reason": result.pass_through_reason,
    }
    if result.stdout_omitted:
        metadata["stdout_omitted"] = True
    if result.stderr_omitted:
        metadata["stderr_omitted"] = True
    if result.redaction_failed:
        metadata["redaction_failed"] = True
    if result.compaction_error:
        metadata["compaction_error"] = result.compaction_error
    if result.bounded_pass_through:
        metadata["bounded_pass_through"] = True
    if result.facts:
        metadata["facts"] = dict(result.facts)
    return metadata


def _argv_from_payload(payload: Mapping[str, Any], command: str | None) -> tuple[str, ...]:
    raw_argv = payload.get("argv")
    if isinstance(raw_argv, list):
        return tuple(str(item) for item in raw_argv)
    if not command:
        return ()
    try:
        return tuple(shlex.split(command))
    except ValueError:
        return tuple(command.split())


def _optional_string(value: Any, *, allow_empty: bool = False) -> str | None:
    if isinstance(value, str) and (allow_empty or value.strip()):
        return value
    return None
