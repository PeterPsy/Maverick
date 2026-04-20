"""Runtime turn submission helpers shared by HTTP and future host surfaces."""

from __future__ import annotations

from dataclasses import replace
import os
from threading import Thread
from typing import TYPE_CHECKING
from uuid import uuid4

from core.providers.service import build_runtime_backend_launch_spec
from core.providers.service import prepare_runtime_skills
from core.providers.service import resolve_provider_for_runtime_session
from core.runtime.attachments import input_text_with_attachment_links
from core.runtime.execution import execute_runtime_turn
from core.runtime.execution_events import RuntimeExecutionEvent
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.service import queue_runtime_turn, record_runtime_event, transition_runtime_turn
from core.skills.service import list_available_workspace_skills, resolve_runtime_skills

if TYPE_CHECKING:
    from core.api.platform_state import PlatformState


def submit_runtime_turn(
    state: PlatformState,
    *,
    session: RuntimeSessionRecord,
    input_text: str,
    client_message_id: str | None = None,
    attachments: list[dict[str, object]] | None = None,
) -> tuple[RuntimeTurnRecord, list[RuntimeEventRecord]]:
    """Queue and execute one runtime turn synchronously."""
    provider, _selection = resolve_provider_for_runtime_session(state.provider_store, session=session)
    turn, events = _queue_turn_with_event(
        state,
        session=session,
        input_text=input_text,
        provider_id=provider.provider_id,
        client_message_id=client_message_id,
        attachments=attachments,
    )
    turn = transition_runtime_turn(state.runtime_store, turn_id=turn.turn_id, target_status="active")
    events.append(_record_turn_started(state, session_id=session.session_id, turn_id=turn.turn_id, provider_id=provider.provider_id))
    try:
        launch_spec = _build_launch_spec_for_execution(state, session=session, provider_id=provider.provider_id)
        provider_input_text = input_text_with_attachment_links(input_text=input_text, attachments=attachments, workspace_root=session.workspace_root)
        result = execute_runtime_turn(
            session=session,
            provider=provider,
            input_text=provider_input_text,
            launch_spec=launch_spec,
            on_provider_thread_id=lambda provider_thread_id: _record_provider_thread_id(state, session=session, provider_id=provider.provider_id, provider_thread_id=provider_thread_id),
            event_sink=lambda event: _record_execution_event(state, session_id=session.session_id, turn_id=turn.turn_id, event=event),
        )
    except Exception as error:
        turn = transition_runtime_turn(state.runtime_store, turn_id=turn.turn_id, target_status="failed", failure_reason=str(error))
        events.append(_record_turn_failed(state, session_id=session.session_id, turn_id=turn.turn_id, provider_id=provider.provider_id, error=str(error)))
        return turn, events

    events.append(_record_final_output(state, session_id=session.session_id, turn_id=turn.turn_id, provider_id=provider.provider_id, output_text=result.output_text, exit_code=result.exit_code))
    turn, terminal_event = _complete_turn_from_exit_code(state, session_id=session.session_id, turn_id=turn.turn_id, provider_id=provider.provider_id, exit_code=result.exit_code)
    events.append(terminal_event)
    return turn, events


def submit_runtime_turn_async(
    state: PlatformState,
    *,
    session: RuntimeSessionRecord,
    input_text: str,
    client_message_id: str | None = None,
    attachments: list[dict[str, object]] | None = None,
) -> tuple[RuntimeTurnRecord, list[RuntimeEventRecord]]:
    """Queue one runtime turn and execute it in a background worker."""
    provider, _selection = resolve_provider_for_runtime_session(state.provider_store, session=session)
    turn, events = _queue_turn_with_event(
        state,
        session=session,
        input_text=input_text,
        provider_id=provider.provider_id,
        client_message_id=client_message_id,
        attachments=attachments,
    )

    def worker() -> None:
        try:
            current = state.runtime_store.get_turn(turn.turn_id)
            if current.status == "cancelled":
                return
            active = transition_runtime_turn(state.runtime_store, turn_id=turn.turn_id, target_status="active")
            _record_turn_started(state, session_id=session.session_id, turn_id=active.turn_id, provider_id=provider.provider_id)
            current_session = state.runtime_store.get_session(session.session_id)
            launch_spec = _build_launch_spec_for_execution(state, session=current_session, provider_id=provider.provider_id)
            provider_input_text = input_text_with_attachment_links(input_text=input_text, attachments=attachments, workspace_root=current_session.workspace_root)
            result = execute_runtime_turn(
                session=current_session,
                provider=provider,
                input_text=provider_input_text,
                launch_spec=launch_spec,
                on_provider_thread_id=lambda provider_thread_id: _record_provider_thread_id(
                    state,
                    session=current_session,
                    provider_id=provider.provider_id,
                    provider_thread_id=provider_thread_id,
                ),
                event_sink=lambda event: _record_execution_event(state, session_id=session.session_id, turn_id=turn.turn_id, event=event),
            )
            current = state.runtime_store.get_turn(turn.turn_id)
            if current.status == "cancelled":
                return
            _record_final_output(
                state,
                session_id=session.session_id,
                turn_id=turn.turn_id,
                provider_id=provider.provider_id,
                output_text=result.output_text,
                exit_code=result.exit_code,
            )
            _complete_turn_from_exit_code(state, session_id=session.session_id, turn_id=turn.turn_id, provider_id=provider.provider_id, exit_code=result.exit_code)
        except Exception as error:
            current = state.runtime_store.get_turn(turn.turn_id)
            if current.status not in {"completed", "failed", "cancelled", "timed-out"}:
                failed = transition_runtime_turn(state.runtime_store, turn_id=turn.turn_id, target_status="failed", failure_reason=str(error))
                _record_turn_failed(state, session_id=session.session_id, turn_id=failed.turn_id, provider_id=provider.provider_id, error=str(error))

    Thread(target=worker, name=f"maverick-runtime-turn-{turn.turn_id}", daemon=True).start()
    return turn, events


def _queue_turn_with_event(
    state: PlatformState,
    *,
    session: RuntimeSessionRecord,
    input_text: str,
    provider_id: str,
    client_message_id: str | None,
    attachments: list[dict[str, object]] | None,
) -> tuple[RuntimeTurnRecord, list[RuntimeEventRecord]]:
    turn = queue_runtime_turn(state.runtime_store, turn_id=str(uuid4()), session_id=session.session_id, input_text=input_text)
    payload: dict[str, object] = {"input_text": input_text, "provider_id": provider_id}
    if client_message_id:
        payload["client_message_id"] = client_message_id
    if attachments:
        payload["attachments"] = attachments
    event = record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session.session_id,
        turn_id=turn.turn_id,
        plane="turn",
        event_type="runtime.turn.queued",
        payload=payload,
        event_bus=state.runtime_event_bus,
    )
    return turn, [event]


def _record_turn_started(state: PlatformState, *, session_id: str, turn_id: str, provider_id: str) -> RuntimeEventRecord:
    return record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn_id,
        plane="turn",
        event_type="runtime.turn.started",
        payload={"provider_id": provider_id},
        event_bus=state.runtime_event_bus,
    )


def _record_provider_thread_id(
    state: PlatformState,
    *,
    session: RuntimeSessionRecord,
    provider_id: str,
    provider_thread_id: str,
) -> RuntimeEventRecord:
    updated = replace(session, provider_id=provider_id, provider_thread_id=provider_thread_id)
    state.runtime_store.save_session(updated)
    return record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session.session_id,
        plane="runtime",
        event_type="runtime.provider_thread.bound",
        payload={"provider_id": provider_id, "provider_thread_id": provider_thread_id},
        event_bus=state.runtime_event_bus,
    )


def _build_launch_spec_for_execution(state: PlatformState, *, session: RuntimeSessionRecord, provider_id: str):
    if os.environ.get("MAVERICK3_RUNTIME_FAKE_RESPONSE") is not None:
        return None
    if provider_id != "codex":
        return None
    spec = build_runtime_backend_launch_spec(
        state.provider_store,
        session=session,
        secret_store=state.secret_store,
        observability_store=state.observability_store,
    )
    skills = (
        resolve_runtime_skills(session, start_path=state.repository_root)
        if session.skill_ids
        else list_available_workspace_skills(workspace_id=session.workspace_id, start_path=state.repository_root)
    )
    if skills:
        prepare_runtime_skills(state.provider_store, session=session, skills=skills)
    return spec


def _record_execution_event(
    state: PlatformState,
    *,
    session_id: str,
    turn_id: str,
    event: RuntimeExecutionEvent,
) -> RuntimeEventRecord:
    return record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn_id,
        plane="turn",
        event_type=event.event_type,
        payload=event.payload,
        event_bus=state.runtime_event_bus,
    )


def _record_final_output(
    state: PlatformState,
    *,
    session_id: str,
    turn_id: str,
    provider_id: str,
    output_text: str,
    exit_code: int,
) -> RuntimeEventRecord:
    return record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn_id,
        plane="turn",
        event_type="runtime.output.final",
        payload={"text": output_text, "provider_id": provider_id, "exit_code": exit_code},
        event_bus=state.runtime_event_bus,
    )


def _complete_turn_from_exit_code(
    state: PlatformState,
    *,
    session_id: str,
    turn_id: str,
    provider_id: str,
    exit_code: int,
) -> tuple[RuntimeTurnRecord, RuntimeEventRecord]:
    if exit_code == 0:
        turn = transition_runtime_turn(state.runtime_store, turn_id=turn_id, target_status="completed")
        event_type = "runtime.turn.completed"
    else:
        turn = transition_runtime_turn(
            state.runtime_store,
            turn_id=turn_id,
            target_status="failed",
            failure_reason=f"Provider exited with code {exit_code}.",
        )
        event_type = "runtime.turn.failed"
    event = record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn.turn_id,
        plane="turn",
        event_type=event_type,
        payload={"provider_id": provider_id, "exit_code": exit_code},
        event_bus=state.runtime_event_bus,
    )
    return turn, event


def _record_turn_failed(state: PlatformState, *, session_id: str, turn_id: str, provider_id: str, error: str) -> RuntimeEventRecord:
    return record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn_id,
        plane="turn",
        event_type="runtime.turn.failed",
        payload={"error": error, "provider_id": provider_id},
        event_bus=state.runtime_event_bus,
    )
