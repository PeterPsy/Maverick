"""Synchronous plain-hosted runtime provider dispatch."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from core.runtime.execution import RuntimeExecutionResult
from core.runtime.plain_hosted_text import execute_plain_hosted_text_turn
from core.runtime.provider_input_context import generalist_orchestration_input_text
from core.runtime.provider_start_handoff import (
    patch_runtime_session_metadata,
    runtime_provider_start_handoff,
)
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.turn_submission_service_output import (
    _record_provider_accepted,
    _record_provider_dispatching,
    _record_provider_turn_start_sent,
)

if TYPE_CHECKING:
    from core.api.platform_state import PlatformState
    from core.runtime.turn_submission_service_output_text import _RuntimeTurnOutputRecorder


def execute_sync_plain_hosted_turn(
    state: PlatformState,
    *,
    session: RuntimeSessionRecord,
    turn: RuntimeTurnRecord,
    input_text: str,
    attachments: list[dict[str, object]] | None,
    output_recorder: _RuntimeTurnOutputRecorder,
    provider_id: str,
    events: list[RuntimeEventRecord],
) -> tuple[RuntimeExecutionResult, str, RuntimeSessionRecord]:
    """Dispatch one sync hosted turn through the bounded provider-start fence."""
    dispatch_started_at = time.perf_counter()
    turn_start_sent_at: float | None = None
    events.append(
        _record_provider_dispatching(
            state,
            session_id=session.session_id,
            turn_id=turn.turn_id,
            provider_id=provider_id,
            runtime_mode=session.runtime_mode,
        )
    )

    def record_turn_start_sent(metadata: dict[str, object]) -> None:
        nonlocal turn_start_sent_at
        turn_start_sent_at = time.perf_counter()
        events.append(
            _record_provider_turn_start_sent(
                state,
                session_id=session.session_id,
                turn_id=turn.turn_id,
                provider_id=str(metadata.get("provider_id") or provider_id),
                runtime_mode=session.runtime_mode,
                metadata=metadata,
            )
        )

    def record_provider_accepted(metadata: dict[str, object]) -> None:
        started_at = turn_start_sent_at if turn_start_sent_at is not None else dispatch_started_at
        events.append(
            _record_provider_accepted(
                state,
                session_id=session.session_id,
                turn_id=turn.turn_id,
                provider_id=str(metadata.get("provider_id") or provider_id),
                runtime_mode=session.runtime_mode,
                elapsed_ms=(time.perf_counter() - started_at) * 1000,
                metadata=metadata,
            )
        )

    with runtime_provider_start_handoff(
        state.runtime_store,
        session_id=session.session_id,
        turn_id=turn.turn_id,
        on_provider_accepted=record_provider_accepted,
    ) as (provider_session, provider_accepted):
        result, routing_decision = execute_plain_hosted_text_turn(
            state,
            session=provider_session,
            turn_id=turn.turn_id,
            input_text=generalist_orchestration_input_text(
                state,
                session=provider_session,
                input_text=input_text,
            ),
            attachments=attachments,
            event_sink=output_recorder.record,
            on_provider_turn_start_sent=record_turn_start_sent,
            on_provider_accepted=provider_accepted,
        )
    selected_provider_id = routing_decision.selected_provider_id or provider_id
    updated_session = patch_runtime_session_metadata(
        state.runtime_store,
        session,
        provider_id=selected_provider_id,
    )
    return result, selected_provider_id, updated_session
