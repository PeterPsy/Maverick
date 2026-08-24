"""Persisted, idempotent handoffs between immutable runtime bindings."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from core.runtime.execution_binding import (
    RuntimeExecutionBinding,
    execution_binding_from_document,
)


ContinuationHandoffPhase = Literal[
    "planned",
    "successor_prepared",
    "provider_state_transferred",
    "predecessor_fenced",
    "thread_rebound",
    "completed",
]

CONTINUATION_HANDOFF_PHASES: tuple[ContinuationHandoffPhase, ...] = (
    "planned",
    "successor_prepared",
    "provider_state_transferred",
    "predecessor_fenced",
    "thread_rebound",
    "completed",
)


@dataclass(frozen=True)
class RuntimeContinuationHandoff:
    """Audit record for one execution-authority continuation fork."""

    handoff_id: str
    workspace_id: str
    predecessor_session_id: str
    successor_session_id: str
    reason_code: str
    source_detail_code: str
    source_binding_digest: str
    target_binding_digest: str
    source_provider_state_revision: int
    source_provider_state_digest: str
    compatible_capabilities: tuple[str, ...]
    compatibility_digest: str
    target_execution_binding: RuntimeExecutionBinding
    phase: ContinuationHandoffPhase
    revision: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


def runtime_continuation_handoff_from_document(
    document: Mapping[str, object],
) -> RuntimeContinuationHandoff:
    """Hydrate one handoff while validating its embedded target binding."""
    payload = dict(document)
    target_binding = payload.get("target_execution_binding")
    if isinstance(target_binding, dict):
        payload["target_execution_binding"] = execution_binding_from_document(target_binding)
    elif not isinstance(target_binding, RuntimeExecutionBinding):
        raise ValueError("Runtime continuation handoff target binding is invalid.")
    payload["compatible_capabilities"] = tuple(
        payload.get("compatible_capabilities", ())
    )
    handoff = RuntimeContinuationHandoff(**payload)
    if handoff.phase not in CONTINUATION_HANDOFF_PHASES:
        raise ValueError("Runtime continuation handoff phase is invalid.")
    if handoff.target_execution_binding.session_id != handoff.successor_session_id:
        raise ValueError("Runtime continuation handoff target session is inconsistent.")
    if handoff.target_execution_binding.binding_digest != handoff.target_binding_digest:
        raise ValueError("Runtime continuation handoff target binding digest is inconsistent.")
    return handoff


def continuation_handoff_phase_index(phase: ContinuationHandoffPhase) -> int:
    """Return the monotonic ordinal for one handoff phase."""
    return CONTINUATION_HANDOFF_PHASES.index(phase)
