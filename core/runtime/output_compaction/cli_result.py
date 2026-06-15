"""Compaction helpers for runtime-token Maverick CLI responses."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import shlex
from typing import Any

from core.runtime.output_compaction.fallbacks import compactor_error_result
from core.runtime.output_compaction.models import (
    ToolOutputCompactionInput,
    ToolOutputCompactionPolicy,
    ToolOutputCompactionResult,
)
from core.runtime.output_compaction.results import savings_ratio
from core.runtime.output_compaction.service import compact_tool_output
from core.runtime.output_compaction.text import byte_len


JsonPath = tuple[str | int, ...]

RUNTIME_CLI_OUTPUT_PROFILE_FULL = "full"
RUNTIME_CLI_OUTPUT_PROFILE_PROVIDER_COMPACT = "provider_compact"
RUNTIME_CLI_OUTPUT_PROFILES = frozenset(
    {
        RUNTIME_CLI_OUTPUT_PROFILE_FULL,
        RUNTIME_CLI_OUTPUT_PROFILE_PROVIDER_COMPACT,
    }
)
RUNTIME_CLI_RESPONSE_COMPACTION_SCOPE = "runtime_cli_response"
RUNTIME_CLI_RESPONSE_COMPACTION_VERSION = 1
RUNTIME_CLI_METADATA_KEYS = {"output_compaction", "runtime_cli_output_compaction"}


def runtime_cli_output_profile(body: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """Return the requested runtime CLI output profile or an error code."""
    if "output_profile" not in body:
        return RUNTIME_CLI_OUTPUT_PROFILE_FULL, None
    raw_profile = body.get("output_profile")
    if not isinstance(raw_profile, str):
        return None, "invalid_output_profile"
    profile = raw_profile.strip()
    if profile not in RUNTIME_CLI_OUTPUT_PROFILES:
        return None, "invalid_output_profile"
    return profile, None


def provider_compact_policy(base_policy: ToolOutputCompactionPolicy | None = None) -> ToolOutputCompactionPolicy:
    """Return the policy used when CLI output is explicitly destined for provider context."""
    policy = base_policy or ToolOutputCompactionPolicy.from_environment()
    return ToolOutputCompactionPolicy(
        enabled=policy.enabled,
        min_original_bytes=min(policy.min_original_bytes, 16_000),
        success_min_savings_ratio=min(policy.success_min_savings_ratio, 0.70),
        failure_min_savings_ratio=min(policy.failure_min_savings_ratio, 0.50),
        target_max_compacted_bytes=min(policy.target_max_compacted_bytes, 10_000),
        failure_target_max_compacted_bytes=min(policy.failure_target_max_compacted_bytes, 16_000),
        failure_tail_lines=policy.failure_tail_lines,
        sanitize_raw_payload=False,
        store_original_artifact=False,
    )


def compact_runtime_cli_result(
    result: Mapping[str, Any],
    *,
    argv: Sequence[str],
    runtime_session_id: str,
    policy: ToolOutputCompactionPolicy | None = None,
) -> dict[str, Any]:
    """Compact large textual fields in a runtime CLI JSON response."""
    active_policy = provider_compact_policy(policy)
    compacted = deepcopy(dict(result))
    if not active_policy.enabled:
        return compacted

    candidates = _collect_large_text_fields(compacted, min_bytes=active_policy.min_original_bytes)
    if not candidates:
        return compacted

    field_results: list[tuple[str, ToolOutputCompactionResult]] = []
    for path, value in candidates:
        field_path = _format_path(path)
        compaction_input = _compaction_input_for_cli_field(
            result=result,
            argv=argv,
            runtime_session_id=runtime_session_id,
            field_path=field_path,
            value=value,
        )
        try:
            field_result = compact_tool_output(compaction_input, policy=active_policy)
        except Exception as error:
            field_result = compactor_error_result(compaction_input, policy=active_policy, error=error)
        replacement = field_result.output if field_result.output is not None else ""
        _set_path(compacted, path, replacement)
        field_results.append((field_path, field_result))

    if not field_results:
        return compacted

    metadata_key = "runtime_cli_output_compaction" if "output_compaction" in compacted else "output_compaction"
    compacted[metadata_key] = _runtime_cli_metadata(field_results)
    return compacted


def _collect_large_text_fields(value: Any, *, min_bytes: int) -> list[tuple[JsonPath, str]]:
    candidates: list[tuple[JsonPath, str]] = []

    def visit(item: Any, path: JsonPath) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                key_text = str(key)
                if key_text in RUNTIME_CLI_METADATA_KEYS:
                    continue
                visit(child, (*path, key_text))
            return
        if isinstance(item, list):
            for index, child in enumerate(item):
                visit(child, (*path, index))
            return
        if isinstance(item, str) and byte_len(item) >= min_bytes:
            candidates.append((path, item))

    visit(value, ())
    return candidates


def _compaction_input_for_cli_field(
    *,
    result: Mapping[str, Any],
    argv: Sequence[str],
    runtime_session_id: str,
    field_path: str,
    value: str,
) -> ToolOutputCompactionInput:
    status_code = result.get("status_code")
    exit_code = status_code if isinstance(status_code, int) and status_code >= 400 else 0
    status = "failed" if isinstance(status_code, int) and status_code >= 400 else "completed"
    return ToolOutputCompactionInput(
        provider_id=None,
        provider_event_type="runtime_cli_response",
        runtime_session_id=runtime_session_id,
        turn_id=None,
        event_type="runtime.cli.response",
        tool_call_id=None,
        tool_name="maverick_cli",
        tool_kind="runtime_cli",
        command=shlex.join(tuple(argv)),
        argv=tuple(argv),
        cwd=None,
        output=value,
        stdout=None,
        stderr=None,
        exit_code=exit_code,
        raw=None,
        metadata={
            "status": status,
            "field_path": field_path,
            "compaction_scope": RUNTIME_CLI_RESPONSE_COMPACTION_SCOPE,
        },
    )


def _runtime_cli_metadata(field_results: Sequence[tuple[str, ToolOutputCompactionResult]]) -> dict[str, Any]:
    original_bytes = sum(result.original_bytes for _path, result in field_results)
    redacted_bytes = sum(result.redacted_bytes for _path, result in field_results)
    compacted_bytes = sum(result.compacted_bytes for _path, result in field_results)
    fields = [path for path, _result in field_results]
    applied = any(result.applied for _path, result in field_results)
    redacted = any(result.redacted for _path, result in field_results)
    pass_through_reasons = sorted({result.pass_through_reason for _path, result in field_results if result.pass_through_reason})
    metadata: dict[str, Any] = {
        "version": RUNTIME_CLI_RESPONSE_COMPACTION_VERSION,
        "scope": RUNTIME_CLI_RESPONSE_COMPACTION_SCOPE,
        "output_profile": RUNTIME_CLI_OUTPUT_PROFILE_PROVIDER_COMPACT,
        "applied": applied,
        "original_bytes": original_bytes,
        "redacted_bytes": redacted_bytes,
        "compacted_bytes": compacted_bytes,
        "savings_ratio": round(savings_ratio(original_bytes, compacted_bytes), 6),
        "redacted": redacted,
        "digest_kind": "redacted_sha256",
        "fields": fields,
        "field_count": len(field_results),
    }
    if pass_through_reasons:
        metadata["pass_through_reasons"] = pass_through_reasons
    if len(field_results) == 1:
        result = field_results[0][1]
        metadata.update(
            {
                "rule_id": result.rule_id,
                "family": result.family,
                "required_savings_ratio": result.required_savings_ratio,
                "target_max_compacted_bytes": result.target_max_compacted_bytes,
                "digest": result.redacted_sha256,
                "pass_through_reason": result.pass_through_reason,
            }
        )
        if result.facts:
            metadata["facts"] = dict(result.facts)
        if result.redaction_failed:
            metadata["redaction_failed"] = True
        if result.compaction_error:
            metadata["compaction_error"] = result.compaction_error
    else:
        metadata["field_results"] = [_runtime_cli_field_metadata(path, result) for path, result in field_results]
    return metadata


def _runtime_cli_field_metadata(field: str, result: ToolOutputCompactionResult) -> dict[str, Any]:
    """Return non-sensitive compaction metadata for one CLI response field."""
    metadata: dict[str, Any] = {
        "field": field,
        "applied": result.applied,
        "rule_id": result.rule_id,
        "family": result.family,
        "original_bytes": result.original_bytes,
        "redacted_bytes": result.redacted_bytes,
        "compacted_bytes": result.compacted_bytes,
        "savings_ratio": round(result.savings_ratio, 6),
        "pass_through_reason": result.pass_through_reason,
        "digest": result.redacted_sha256,
    }
    if result.redaction_failed:
        metadata["redaction_failed"] = True
    if result.compaction_error:
        metadata["compaction_error"] = result.compaction_error
    return metadata


def _set_path(root: Any, path: JsonPath, value: str) -> None:
    parent = root
    for part in path[:-1]:
        parent = parent[part]
    parent[path[-1]] = value


def _format_path(path: JsonPath) -> str:
    rendered = ""
    for part in path:
        if isinstance(part, int):
            rendered += f"[{part}]"
            continue
        rendered = part if not rendered else f"{rendered}.{part}"
    return rendered
