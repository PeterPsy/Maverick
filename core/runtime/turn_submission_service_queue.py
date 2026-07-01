"""Runtime turn queueing and idempotent handoff helpers."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING
from uuid import uuid4

from core.runtime.plain_hosted_text import queue_provider_id_for_session
from core.runtime.client_message_claims import RuntimeClientMessageClaim
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.service import queue_runtime_turn_if_client_message_absent, record_runtime_event
from core.runtime.thread_catalog_events import mark_thread_user_message_queued
from core.runtime.thread_title_jobs import schedule_runtime_thread_title_generation, thread_title_input_hash

if TYPE_CHECKING:
    from core.api.platform_state import PlatformState


def _queue_turn_with_event(
    state: PlatformState,
    *,
    session: RuntimeSessionRecord,
    input_text: str,
    provider_id: str | None,
    client_message_id: str | None,
    attachments: list[dict[str, object]] | None,
    app_references: list[dict[str, object]] | None,
    turn_id: str | None = None,
    received_perf_counter: float | None = None,
) -> tuple[RuntimeTurnRecord, list[RuntimeEventRecord]]:
    turn, events, _created = _queue_turn_with_event_result(
        state,
        session=session,
        input_text=input_text,
        provider_id=provider_id,
        client_message_id=client_message_id,
        attachments=attachments,
        app_references=app_references,
        turn_id=turn_id,
        received_perf_counter=received_perf_counter,
    )
    return turn, events


def _queue_turn_with_event_result(
    state: PlatformState,
    *,
    session: RuntimeSessionRecord,
    input_text: str,
    provider_id: str | None,
    client_message_id: str | None,
    attachments: list[dict[str, object]] | None,
    app_references: list[dict[str, object]] | None,
    turn_id: str | None = None,
    received_perf_counter: float | None = None,
    client_message_claim: RuntimeClientMessageClaim | None = None,
) -> tuple[RuntimeTurnRecord, list[RuntimeEventRecord], bool]:
    normalized_provider_id = (provider_id or queue_provider_id_for_session(session)).strip()
    turn, created = queue_runtime_turn_if_client_message_absent(
        state.runtime_store,
        turn_id=turn_id or str(uuid4()),
        session_id=session.session_id,
        input_text=input_text,
        client_message_id=client_message_id,
        client_message_claim=client_message_claim,
    )
    if not created:
        return turn, _turn_events_for_response(state, turn, wait_seconds=2.0), False
    payload: dict[str, object] = {"input_text": input_text, "provider_id": normalized_provider_id}
    if client_message_id:
        payload["client_message_id"] = client_message_id
    if attachments:
        payload["attachments"] = attachments
    if app_references:
        payload["app_references"] = app_references
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
    _record_receive_to_queued_metric(
        state,
        session=session,
        turn=turn,
        queued_event=event,
        received_perf_counter=received_perf_counter,
    )
    title_input_hash = thread_title_input_hash(
        input_text,
        attachments=attachments,
        app_references=app_references,
    )
    thread = mark_thread_user_message_queued(
        state,
        workspace_id=session.workspace_id,
        runtime_session_id=session.session_id,
        input_text=input_text,
        attachments=attachments,
        app_references=app_references,
        title_generation_input_hash=title_input_hash,
        now=turn.created_at,
    )
    schedule_runtime_thread_title_generation(
        state,
        thread=thread,
        input_text=input_text,
        attachments=attachments,
        app_references=app_references,
    )
    return turn, [event], True


def _turn_events_for_response(state: PlatformState, turn: RuntimeTurnRecord, *, wait_seconds: float = 0.0) -> list[RuntimeEventRecord]:
    deadline = time.monotonic() + max(0.0, wait_seconds)
    while True:
        events = [
            event
            for event in state.runtime_store.list_events(turn.session_id)
            if event.turn_id == turn.turn_id and event.event_type == "runtime.turn.queued"
        ][:1]
        if events or time.monotonic() >= deadline:
            return events
        time.sleep(0.01)


def _record_receive_to_queued_metric(
    state: PlatformState,
    *,
    session: RuntimeSessionRecord,
    turn: RuntimeTurnRecord,
    queued_event: RuntimeEventRecord,
    received_perf_counter: float | None,
) -> RuntimeEventRecord | None:
    if received_perf_counter is None:
        return None
    elapsed_ms = (time.perf_counter() - received_perf_counter) * 1000
    return record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session.session_id,
        turn_id=turn.turn_id,
        plane="turn",
        event_type="runtime.turn.receive_to_queued",
        payload={
            "queued_event_id": queued_event.event_id,
            "receive_to_queued_ms": round(elapsed_ms, 3),
        },
        event_bus=state.runtime_event_bus,
    )
