"""Result builders for runtime tool-output compaction."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
from typing import Any

from core.runtime.output_compaction.event_payloads import COMPACTION_SCOPE
from core.runtime.output_compaction.models import (
    RuleSelection,
    ToolOutputCompactionInput,
    ToolOutputCompactionPolicy,
    ToolOutputCompactionResult,
)
from core.runtime.output_compaction.text import byte_len, truncate_middle_bytes


REDACTION_FAILURE_PLACEHOLDER = "[tool output omitted: redaction_failed]"
BOUNDED_PASS_THROUGH_MARKER = "[tool output bounded]"


def pass_through_result(
    compaction_input: ToolOutputCompactionInput,
    *,
    raw: Mapping[str, Any] | None,
    redacted_fields: Mapping[str, str],
    redacted_raw_fields: tuple[tuple[str, str], ...] = (),
    applied: bool,
    pass_through_reason: str,
    rule_id: str | None,
    family: str | None,
    original_bytes: int,
    redacted_bytes: int,
    required_savings_ratio: float,
    target_max_compacted_bytes: int,
    digest: str,
    fields: tuple[str, ...],
    facts: Mapping[str, Any],
    compaction_error: str = "",
) -> ToolOutputCompactionResult:
    """Build a redacted pass-through result."""
    bounded_fields, stdout_omitted, stderr_omitted, bounded_pass_through = _bounded_pass_through_fields(
        compaction_input,
        redacted_fields=redacted_fields,
        redacted_raw_fields=redacted_raw_fields,
        pass_through_reason=pass_through_reason,
        rule_id=rule_id,
        family=family,
        original_bytes=original_bytes,
        redacted_bytes=redacted_bytes,
        target_max_compacted_bytes=target_max_compacted_bytes,
        digest=digest,
        facts=facts,
    )
    compacted_bytes = sum(byte_len(value) for value in bounded_fields.values())
    return ToolOutputCompactionResult(
        output=bounded_fields.get("output", redacted_fields.get("output", compaction_input.output)),
        stdout=bounded_fields.get("stdout", redacted_fields.get("stdout", compaction_input.stdout)),
        stderr=bounded_fields.get("stderr", redacted_fields.get("stderr", compaction_input.stderr)),
        raw=raw,
        applied=applied,
        pass_through_reason=pass_through_reason,
        rule_id=rule_id,
        family=family,
        original_bytes=original_bytes,
        redacted_bytes=redacted_bytes,
        compacted_bytes=compacted_bytes,
        savings_ratio=savings_ratio(original_bytes, compacted_bytes),
        required_savings_ratio=required_savings_ratio,
        target_max_compacted_bytes=target_max_compacted_bytes,
        redacted=True,
        redacted_sha256=digest,
        fields=fields,
        facts=facts,
        stdout_omitted=stdout_omitted,
        stderr_omitted=stderr_omitted,
        compaction_error=compaction_error,
        bounded_pass_through=bounded_pass_through,
    )


def redaction_failure_result(
    compaction_input: ToolOutputCompactionInput,
    *,
    raw: Mapping[str, Any] | None,
    original_bytes: int,
    fields: tuple[str, ...],
    policy: ToolOutputCompactionPolicy,
) -> ToolOutputCompactionResult:
    """Build a bounded result for fatal redaction failures."""
    failed = is_failure(compaction_input)
    target = policy.failure_target_max_compacted_bytes if failed else policy.target_max_compacted_bytes
    required = policy.failure_min_savings_ratio if failed else policy.success_min_savings_ratio
    placeholder = REDACTION_FAILURE_PLACEHOLDER
    digest = redacted_digest(placeholder)
    return ToolOutputCompactionResult(
        output=placeholder if compaction_input.output is not None or not compaction_input.stdout else compaction_input.output,
        stdout=placeholder if compaction_input.output is None and compaction_input.stdout is not None else ("" if compaction_input.stdout is not None else None),
        stderr="" if compaction_input.stderr is not None else None,
        raw={"has_omitted_provider_payload": True, "redaction_failed": True} if raw is None else {**dict(raw), "redaction_failed": True},
        applied=False,
        pass_through_reason="redaction_failed",
        rule_id=None,
        family=None,
        original_bytes=original_bytes,
        redacted_bytes=byte_len(placeholder),
        compacted_bytes=byte_len(placeholder),
        savings_ratio=savings_ratio(original_bytes, byte_len(placeholder)),
        required_savings_ratio=required,
        target_max_compacted_bytes=target,
        redacted=False,
        redacted_sha256=digest,
        fields=fields,
        facts={},
        stdout_omitted=compaction_input.stdout is not None and compaction_input.output is not None,
        stderr_omitted=compaction_input.stderr is not None,
        redaction_failed=True,
    )


def unchanged_result(
    compaction_input: ToolOutputCompactionInput,
    *,
    raw: Mapping[str, Any] | None,
    policy: ToolOutputCompactionPolicy,
    redacted: bool = False,
    fields: tuple[str, ...] = (),
) -> ToolOutputCompactionResult:
    """Build a no-op result for tool calls without output text."""
    return ToolOutputCompactionResult(
        output=compaction_input.output,
        stdout=compaction_input.stdout,
        stderr=compaction_input.stderr,
        raw=raw,
        applied=False,
        pass_through_reason="no_text_fields",
        rule_id=None,
        family=None,
        original_bytes=0,
        redacted_bytes=0,
        compacted_bytes=0,
        savings_ratio=0.0,
        required_savings_ratio=policy.success_min_savings_ratio,
        target_max_compacted_bytes=policy.target_max_compacted_bytes,
        redacted=redacted,
        redacted_sha256="",
        fields=fields,
    )


def compacted_header(
    *,
    selection: RuleSelection,
    scope: str,
    original_bytes: int,
    redacted_bytes: int,
    compacted_bytes: int,
    savings_ratio_value: float,
    digest: str,
    facts: Mapping[str, Any],
) -> str:
    """Build the text header for compacted tool output."""
    summary = " ".join(f"{key}={value}" for key, value in sorted(facts.items()) if value not in (None, "", 0))
    lines = [
        "[tool output compacted]",
        f"scope: {scope}",
        f"rule: {selection.rule_id}",
        f"original_bytes: {original_bytes}",
        f"redacted_bytes: {redacted_bytes}",
        f"compacted_bytes: {compacted_bytes}",
        f"savings_ratio: {savings_ratio_value:.6f}",
        f"redacted_sha256: {digest}",
    ]
    if summary:
        lines.append(f"summary: {summary}")
    return "\n".join(lines)


def build_compacted_text(
    *,
    selection: RuleSelection,
    compaction_input: ToolOutputCompactionInput,
    reduced_text: str,
    facts: Mapping[str, Any],
    original_bytes: int,
    redacted_bytes: int,
    target_max_compacted_bytes: int,
    digest: str,
) -> tuple[str, int, float]:
    """Build compacted text whose header byte counts match final metadata."""
    scope = str(compaction_input.metadata.get("compaction_scope") or COMPACTION_SCOPE)
    stable_text = truncate_middle_bytes(reduced_text, target_max_compacted_bytes)
    stable_bytes = byte_len(stable_text)
    stable_ratio = savings_ratio(original_bytes, stable_bytes)
    header_facts = {**dict(facts), **exit_code_fact(compaction_input)}

    for _attempt in range(8):
        candidate = (
            compacted_header(
                selection=selection,
                scope=scope,
                original_bytes=original_bytes,
                redacted_bytes=redacted_bytes,
                compacted_bytes=stable_bytes,
                savings_ratio_value=stable_ratio,
                digest=digest,
                facts=header_facts,
            )
            + "\n\n"
            + reduced_text
        )
        candidate = truncate_middle_bytes(candidate, target_max_compacted_bytes)
        candidate_bytes = byte_len(candidate)
        candidate_ratio = savings_ratio(original_bytes, candidate_bytes)
        if candidate_bytes == stable_bytes and f"{candidate_ratio:.6f}" == f"{stable_ratio:.6f}":
            return candidate, candidate_bytes, candidate_ratio
        stable_text = candidate
        stable_bytes = candidate_bytes
        stable_ratio = candidate_ratio
    return stable_text, stable_bytes, stable_ratio


def _bounded_pass_through_fields(
    compaction_input: ToolOutputCompactionInput,
    *,
    redacted_fields: Mapping[str, str],
    redacted_raw_fields: tuple[tuple[str, str], ...],
    pass_through_reason: str,
    rule_id: str | None,
    family: str | None,
    original_bytes: int,
    redacted_bytes: int,
    target_max_compacted_bytes: int,
    digest: str,
    facts: Mapping[str, Any],
) -> tuple[dict[str, str], bool, bool, bool]:
    current_fields = {key: value for key, value in redacted_fields.items()}
    current_bytes = sum(byte_len(value) for value in current_fields.values())
    if current_fields and current_bytes <= target_max_compacted_bytes:
        return current_fields, False, False, False
    if not current_fields and not redacted_raw_fields:
        return current_fields, False, False, False

    body_text = _combined_labeled_text(redacted_fields, redacted_raw_fields).strip()
    header_facts = {**dict(facts), **exit_code_fact(compaction_input)}
    scope = str(compaction_input.metadata.get("compaction_scope") or COMPACTION_SCOPE)
    header_lines = [
        BOUNDED_PASS_THROUGH_MARKER,
        f"scope: {scope}",
        f"pass_through_reason: {pass_through_reason}",
        f"original_bytes: {original_bytes}",
        f"redacted_bytes: {redacted_bytes}",
        f"target_max_compacted_bytes: {target_max_compacted_bytes}",
        f"redacted_sha256: {digest}",
    ]
    if rule_id:
        header_lines.insert(2, f"rule: {rule_id}")
    if family:
        header_lines.insert(3 if rule_id else 2, f"family: {family}")
    summary = " ".join(f"{key}={value}" for key, value in sorted(header_facts.items()) if value not in (None, "", 0))
    if summary:
        header_lines.append(f"summary: {summary}")
    header = "\n".join(header_lines)

    if body_text:
        body_budget = max(0, target_max_compacted_bytes - byte_len(header) - 2)
        body = truncate_middle_bytes(
            body_text,
            body_budget,
            marker="\n[... omitted for bounded pass-through ...]\n",
        )
        bounded = f"{header}\n\n{body}" if body else header
    else:
        bounded = header
    bounded = truncate_middle_bytes(
        bounded,
        target_max_compacted_bytes,
        marker="\n[... omitted for bounded pass-through ...]\n",
    )
    fields = {"output": bounded}
    if compaction_input.stdout is not None:
        fields["stdout"] = ""
    if compaction_input.stderr is not None:
        fields["stderr"] = ""
    return fields, compaction_input.stdout is not None, compaction_input.stderr is not None, True


def _combined_labeled_text(fields: Mapping[str, str], raw_fields: tuple[tuple[str, str], ...]) -> str:
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


def is_failure(compaction_input: ToolOutputCompactionInput) -> bool:
    """Return true when tool output should use diagnostic failure policy."""
    status = str(compaction_input.metadata.get("status") or "").strip().lower()
    return status == "failed" or (isinstance(compaction_input.exit_code, int) and compaction_input.exit_code != 0)


def savings_ratio(original_bytes: int, compacted_bytes: int) -> float:
    """Return savings ratio from original to compacted byte count."""
    if original_bytes <= 0:
        return 0.0
    return max(0.0, (original_bytes - compacted_bytes) / original_bytes)


def redacted_digest(value: str) -> str:
    """Return the event-safe digest for already-redacted text."""
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def exit_code_fact(compaction_input: ToolOutputCompactionInput) -> dict[str, int]:
    """Return exit code fact metadata when present."""
    return {"exit_code": compaction_input.exit_code} if compaction_input.exit_code is not None else {}
