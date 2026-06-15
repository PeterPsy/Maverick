"""Models for runtime tool-output payload compaction."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from typing import Any, Mapping


@dataclass(frozen=True)
class ToolOutputCompactionContext:
    """Runtime identity attached to one compaction decision."""

    session_id: str | None = None
    turn_id: str | None = None


@dataclass(frozen=True)
class ToolOutputCompactionPolicy:
    """Operational policy for runtime event payload compaction."""

    enabled: bool = True
    min_original_bytes: int = 50_000
    success_min_savings_ratio: float = 0.95
    failure_min_savings_ratio: float = 0.70
    target_max_compacted_bytes: int = 12_000
    failure_target_max_compacted_bytes: int = 24_000
    failure_tail_lines: int = 80
    sanitize_raw_payload: bool = True
    store_original_artifact: bool = False

    @classmethod
    def from_environment(cls) -> "ToolOutputCompactionPolicy":
        """Build the policy from runtime environment flags."""
        raw_enabled = os.environ.get("MAVERICK_RUNTIME_OUTPUT_COMPACTION", "1").strip().lower()
        enabled = raw_enabled not in {"0", "false", "no", "off", "disabled"}
        return cls(enabled=enabled)


@dataclass(frozen=True)
class ToolOutputCompactionInput:
    """Normalized tool-call fields consumed by the reducer."""

    provider_id: str | None
    provider_event_type: str | None
    runtime_session_id: str | None
    turn_id: str | None
    event_type: str
    tool_call_id: str | None
    tool_name: str | None
    tool_kind: str | None
    command: str | None
    argv: tuple[str, ...]
    cwd: str | None
    output: str | None
    stdout: str | None
    stderr: str | None
    exit_code: int | None
    raw: Mapping[str, Any] | None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuleSelection:
    """Selected compaction rule metadata."""

    rule_id: str
    family: str


@dataclass(frozen=True)
class ReducerOutput:
    """Text and non-sensitive facts returned by a reducer."""

    text: str
    facts: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolOutputCompactionResult:
    """Compacted event fields plus stable event metadata."""

    output: str | None
    stdout: str | None
    stderr: str | None
    raw: Mapping[str, Any] | None
    applied: bool
    pass_through_reason: str
    rule_id: str | None
    family: str | None
    original_bytes: int
    redacted_bytes: int
    compacted_bytes: int
    savings_ratio: float
    required_savings_ratio: float
    target_max_compacted_bytes: int
    redacted: bool
    redacted_sha256: str
    fields: tuple[str, ...]
    facts: Mapping[str, Any] = field(default_factory=dict)
    stdout_omitted: bool = False
    stderr_omitted: bool = False
    redaction_failed: bool = False
    compaction_error: str = ""
