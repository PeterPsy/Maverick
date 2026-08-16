"""Runtime turn queueing and idempotent handoff helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import time
from typing import TYPE_CHECKING, Any
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


@dataclass
class RuntimeTurnSubmissionTiming:
    """Request-local latency spans for the HTTP receive to queue path."""

    received_perf_counter: float | None = None
    client_submission_started_at: datetime | None = None
    client_submission_metrics: dict[str, Any] = field(default_factory=dict)
    _durations_ms: dict[str, float] = field(default_factory=dict)
    _queue_recorded_perf_counter: float | None = None

    def record_duration_ms(self, name: str, started_perf_counter: float) -> None:
        if self.received_perf_counter is None:
            return
        self._durations_ms[name] = (time.perf_counter() - started_perf_counter) * 1000

    def record_queue_completed(self, started_perf_counter: float) -> None:
        if self.received_perf_counter is None:
            return
        now = time.perf_counter()
        self._durations_ms["queue_turn_ms"] = (now - started_perf_counter) * 1000
        self._queue_recorded_perf_counter = now

    def record_post_queue_response_ms(self) -> float | None:
        if self.received_perf_counter is None or self._queue_recorded_perf_counter is None:
            return None
        value = (time.perf_counter() - self._queue_recorded_perf_counter) * 1000
        self._durations_ms["post_queue_response_ms"] = value
        return value

    def payload(self, *names: str) -> dict[str, float]:
        payload: dict[str, float] = {}
        for name in names:
            value = self._durations_ms.get(name)
            if value is not None:
                payload[name] = round(value, 3)
        return payload


def runtime_turn_submission_timing(received_perf_counter: float | None) -> RuntimeTurnSubmissionTiming | None:
    if received_perf_counter is None:
        return None
    return RuntimeTurnSubmissionTiming(received_perf_counter=received_perf_counter)


def _queue_turn_with_event(
    state: PlatformState,
    *,
    session: RuntimeSessionRecord,
    input_text: str,
    provider_id: str | None,
    client_message_id: str | None,
    attachments: list[dict[str, object]] | None,
    app_references: list[dict[str, object]] | None,
    invoked_skill_ids: list[str] | None = None,
    turn_id: str | None = None,
    received_perf_counter: float | None = None,
    submission_timing: RuntimeTurnSubmissionTiming | None = None,
) -> tuple[RuntimeTurnRecord, list[RuntimeEventRecord]]:
    turn, events, _created = _queue_turn_with_event_result(
        state,
        session=session,
        input_text=input_text,
        provider_id=provider_id,
        client_message_id=client_message_id,
        attachments=attachments,
        app_references=app_references,
        invoked_skill_ids=invoked_skill_ids,
        turn_id=turn_id,
        received_perf_counter=received_perf_counter,
        submission_timing=submission_timing,
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
    invoked_skill_ids: list[str] | None = None,
    turn_id: str | None = None,
    received_perf_counter: float | None = None,
    client_message_claim: RuntimeClientMessageClaim | None = None,
    submission_timing: RuntimeTurnSubmissionTiming | None = None,
) -> tuple[RuntimeTurnRecord, list[RuntimeEventRecord], bool]:
    normalized_provider_id = (provider_id or queue_provider_id_for_session(session)).strip()
    timing = submission_timing or runtime_turn_submission_timing(received_perf_counter)
    queue_started_at = time.perf_counter()
    turn, created = queue_runtime_turn_if_client_message_absent(
        state.runtime_store,
        turn_id=turn_id or str(uuid4()),
        session_id=session.session_id,
        input_text=input_text,
        client_message_id=client_message_id,
        invoked_skill_ids=invoked_skill_ids,
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
    if invoked_skill_ids:
        payload["invoked_skill_ids"] = list(invoked_skill_ids)
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
    if timing is not None:
        timing.record_queue_completed(queue_started_at)
    _record_receive_to_queued_metric(
        state,
        session=session,
        turn=turn,
        queued_event=event,
        received_perf_counter=received_perf_counter,
        submission_timing=timing,
    )
    title_input_hash = thread_title_input_hash(
        input_text,
        attachments=attachments,
        app_references=app_references,
    )
    thread_catalog_started_at = time.perf_counter()
    _record_thread_user_message_queued_started(
        state,
        session=session,
        turn=turn,
        provider_id=normalized_provider_id,
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
    _record_thread_user_message_queued_completed(
        state,
        session=session,
        turn=turn,
        provider_id=normalized_provider_id,
        elapsed_ms=(time.perf_counter() - thread_catalog_started_at) * 1000,
        thread_id=thread.thread_id if thread is not None else "",
        attachments=attachments,
        app_references=app_references,
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
    submission_timing: RuntimeTurnSubmissionTiming | None = None,
) -> RuntimeEventRecord | None:
    timing = submission_timing or runtime_turn_submission_timing(received_perf_counter)
    if timing is None or timing.received_perf_counter is None:
        return None
    elapsed_ms = (time.perf_counter() - timing.received_perf_counter) * 1000
    payload: dict[str, object] = {
        "queued_event_id": queued_event.event_id,
        "receive_to_queued_ms": round(elapsed_ms, 3),
    }
    payload.update(
        timing.payload(
            "claim_ms",
            "session_create_ms",
            "reference_validate_ms",
            "queue_turn_ms",
        )
    )
    payload.update(timing.client_submission_metrics)
    click_to_queued_ms = _client_click_to_queued_ms(
        queued_event_created_at=queued_event.created_at,
        client_submission_started_at=timing.client_submission_started_at,
    )
    if click_to_queued_ms is not None:
        payload["client_click_to_queued_ms"] = round(click_to_queued_ms, 3)
    return record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session.session_id,
        turn_id=turn.turn_id,
        plane="turn",
        event_type="runtime.turn.receive_to_queued",
        payload=payload,
        event_bus=state.runtime_event_bus,
    )


def _client_click_to_queued_ms(
    *,
    queued_event_created_at,
    client_submission_started_at: datetime | None,
) -> float | None:
    if client_submission_started_at is None:
        return None
    elapsed_ms = (queued_event_created_at - client_submission_started_at).total_seconds() * 1000
    if elapsed_ms < 0 or elapsed_ms > 300_000:
        return None
    return elapsed_ms


def _record_thread_user_message_queued_started(
    state: PlatformState,
    *,
    session: RuntimeSessionRecord,
    turn: RuntimeTurnRecord,
    provider_id: str,
    attachments: list[dict[str, object]] | None,
    app_references: list[dict[str, object]] | None,
) -> RuntimeEventRecord:
    app_reference_count, storage_reference_count = _reference_counts(app_references)
    return record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session.session_id,
        turn_id=turn.turn_id,
        plane="turn",
        event_type="runtime.turn.thread_user_message_queued_started",
        payload={
            "provider_id": provider_id,
            "attachment_count": _attachment_count(attachments),
            "app_reference_count": app_reference_count,
            "storage_reference_count": storage_reference_count,
        },
        event_bus=state.runtime_event_bus,
    )


def _record_thread_user_message_queued_completed(
    state: PlatformState,
    *,
    session: RuntimeSessionRecord,
    turn: RuntimeTurnRecord,
    provider_id: str,
    elapsed_ms: float,
    thread_id: str,
    attachments: list[dict[str, object]] | None,
    app_references: list[dict[str, object]] | None,
) -> RuntimeEventRecord:
    app_reference_count, storage_reference_count = _reference_counts(app_references)
    payload: dict[str, object] = {
        "provider_id": provider_id,
        "thread_catalog_queued_ms": round(elapsed_ms, 3),
        "attachment_count": _attachment_count(attachments),
        "app_reference_count": app_reference_count,
        "storage_reference_count": storage_reference_count,
    }
    if thread_id:
        payload["thread_id"] = thread_id
    return record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session.session_id,
        turn_id=turn.turn_id,
        plane="turn",
        event_type="runtime.turn.thread_user_message_queued_completed",
        payload=payload,
        event_bus=state.runtime_event_bus,
    )


def _reference_counts(app_references: list[dict[str, object]] | None) -> tuple[int, int]:
    references = [item for item in app_references or [] if isinstance(item, dict)]
    storage_count = sum(1 for item in references if str(item.get("app_id") or "").strip().lower() == "storage")
    return len(references), storage_count


def _attachment_count(attachments: list[dict[str, object]] | None) -> int:
    return len([item for item in attachments or [] if isinstance(item, dict)])


def record_turn_post_queue_response_metric(
    state: PlatformState,
    *,
    session: RuntimeSessionRecord,
    turn: RuntimeTurnRecord,
    submission_timing: RuntimeTurnSubmissionTiming | None,
) -> RuntimeEventRecord | None:
    if submission_timing is None:
        return None
    post_queue_response_ms = submission_timing.record_post_queue_response_ms()
    if post_queue_response_ms is None:
        return None
    return record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session.session_id,
        turn_id=turn.turn_id,
        plane="turn",
        event_type="runtime.turn.post_queue_response",
        payload={"post_queue_response_ms": round(post_queue_response_ms, 3)},
        event_bus=state.runtime_event_bus,
    )
