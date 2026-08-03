"""Runtime bridge and generalist steering for orchestrated runs."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable

from core.inter_agent.errors import InterAgentOperationError
from core.inter_agent.models import InterAgentParticipantRecord
from core.inter_agent.service import InterAgentService


ParticipantTurnExecutor = Callable[[InterAgentParticipantRecord, str, str], str]
TERMINAL_RUNTIME_TURN_STATUSES = {"completed", "failed", "cancelled", "timed-out"}
GENERALIST_HANDOFF_WAIT_TIMEOUT_SECONDS = 6 * 60 * 60
GENERALIST_HANDOFF_POLL_SECONDS = 0.1


@dataclass(frozen=True)
class GeneralistHandoff:
    input_text: str
    analysis_text: str
    runtime_event_id: str


def runtime_turn_executor(service: InterAgentService, state: Any, run: Any) -> ParticipantTurnExecutor:
    def execute(participant: InterAgentParticipantRecord, prompt: str, client_message_id: str) -> str:
        current = service.store.get_participant(
            participant.participant_id,
            workspace_id=run.workspace_id,
            run_id=run.run_id,
        )
        if not current.runtime_session_id:
            current, _session, _created = service.spawn_participant_runtime_session(
                state.runtime_store,
                workspace_id=run.workspace_id,
                run_id=run.run_id,
                participant_id=current.participant_id,
                owner_user_id=run.created_by_user_id,
                created_by_user_id=run.created_by_user_id,
            )
        current, _turn, events = service.send_runtime_message(
            state,
            workspace_id=run.workspace_id,
            run_id=run.run_id,
            participant_id=current.participant_id,
            input_text=prompt,
            client_message_id=client_message_id,
            async_requested=False,
        )
        output = _runtime_output_text(events)
        if not output:
            raise InterAgentOperationError(f"Participant `{current.participant_id}` returned no final output.")
        return output

    return execute


def prepare_generalist_handoff(
    service: InterAgentService,
    state: Any,
    run: Any,
    *,
    timeout_seconds: float = GENERALIST_HANDOFF_WAIT_TIMEOUT_SECONDS,
    poll_seconds: float = GENERALIST_HANDOFF_POLL_SECONDS,
) -> GeneralistHandoff:
    """Wait for and persist the source generalist's completed launch analysis."""
    runtime_store = getattr(state, "runtime_store", None)
    if runtime_store is None or not run.source_runtime_turn_id:
        raise InterAgentOperationError("Orchestrated runs require an available source generalist turn.")
    persisted = _persisted_handoff(service, run)
    if persisted is not None:
        return persisted
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while True:
        latest_run = service.store.get_run(run.run_id, workspace_id=run.workspace_id)
        if latest_run.status in {"cancelled", "failed"}:
            raise InterAgentOperationError("Orchestration stopped before the generalist handoff was ready.")
        turn = runtime_store.get_turn(run.source_runtime_turn_id)
        events = [
            event
            for event in runtime_store.list_events(run.root_runtime_session_id)
            if event.turn_id == run.source_runtime_turn_id
        ]
        if turn.status in TERMINAL_RUNTIME_TURN_STATUSES:
            if turn.status != "completed":
                raise InterAgentOperationError(
                    f"Source generalist turn ended with status `{turn.status}` before preparing the handoff."
                )
            final_event = _last_final_event(events)
            analysis_text = _runtime_event_text(final_event) if final_event is not None else ""
            if not analysis_text:
                raise InterAgentOperationError("Source generalist turn completed without a final handoff output.")
            input_text = str(getattr(turn, "input_text", "") or "").strip()
            if not input_text:
                raise InterAgentOperationError("Source generalist turn has no user request to orchestrate.")
            handoff = GeneralistHandoff(
                input_text=input_text[:20000],
                analysis_text=analysis_text[:20000],
                runtime_event_id=str(final_event.event_id),
            )
            service.record_event(
                latest_run,
                event_type="inter_agent.generalist.handoff_prepared",
                participant_id=latest_run.orchestrator_participant_id,
                runtime_turn_id=run.source_runtime_turn_id,
                runtime_event_id=handoff.runtime_event_id,
                visibility_plane="detail",
                correlation_id=f"{run.run_id}:generalist-handoff",
                idempotency_key=f"{run.run_id}:generalist.handoff:{handoff.runtime_event_id}",
                payload={
                    "source_runtime_turn_id": run.source_runtime_turn_id,
                    "input_text": handoff.input_text,
                    "analysis_text": handoff.analysis_text,
                },
            )
            return handoff
        if time.monotonic() >= deadline:
            raise InterAgentOperationError("Timed out waiting for the source generalist handoff.")
        time.sleep(max(0.0, poll_seconds))


def sync_generalist_directives(
    service: InterAgentService,
    state: Any,
    run: Any,
    *,
    timeout_seconds: float = GENERALIST_HANDOFF_WAIT_TIMEOUT_SECONDS,
    poll_seconds: float = GENERALIST_HANDOFF_POLL_SECONDS,
) -> None:
    """Resolve linked later generalist turns before an orchestrator safe point."""
    runtime_store = getattr(state, "runtime_store", None)
    if runtime_store is None:
        return
    for link in service.pending_generalist_directive_links(run):
        turn_id = str(link.runtime_turn_id or "").strip()
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        while True:
            latest_run = service.store.get_run(run.run_id, workspace_id=run.workspace_id)
            if latest_run.status in {"cancelled", "failed"}:
                raise InterAgentOperationError("Orchestration stopped while waiting for generalist steering.")
            turn = runtime_store.get_turn(turn_id)
            if turn.status in TERMINAL_RUNTIME_TURN_STATUSES:
                if turn.status == "completed":
                    events = [
                        event
                        for event in runtime_store.list_events(run.root_runtime_session_id)
                        if event.turn_id == turn_id
                    ]
                    final_event = _last_final_event(events)
                    text = _runtime_event_text(final_event) if final_event is not None else ""
                    if text:
                        directive = service.record_directive(
                            workspace_id=run.workspace_id,
                            run_id=run.run_id,
                            text=text[:6000],
                            source_kind="root_generalist",
                            source_runtime_event_id=str(final_event.event_id),
                            source_runtime_turn_id=turn_id,
                            idempotency_key=f"{run.run_id}:root-directive:{final_event.event_id}",
                        )
                        service.resolve_generalist_directive_link(
                            latest_run,
                            link,
                            status="delivered",
                            directive_id=str(directive.payload.get("directive_id") or ""),
                        )
                        break
                service.resolve_generalist_directive_link(latest_run, link, status="ignored")
                break
            if time.monotonic() >= deadline:
                raise InterAgentOperationError("Timed out waiting for linked generalist steering.")
            time.sleep(max(0.0, poll_seconds))


def _runtime_output_text(events: list[Any]) -> str:
    final = ""
    for event in events:
        if getattr(event, "event_type", "") != "runtime.output.final":
            continue
        payload = event.payload if isinstance(getattr(event, "payload", None), dict) else {}
        text = payload.get("complete_text") or payload.get("text")
        if isinstance(text, str) and text.strip():
            final = text.strip()
    return final


def _runtime_event_text(event: Any) -> str:
    payload = event.payload if isinstance(getattr(event, "payload", None), dict) else {}
    for key in ("complete_text", "text", "summary", "label", "output"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _last_final_event(events: list[Any]) -> Any | None:
    finals = [event for event in events if getattr(event, "event_type", "") == "runtime.output.final"]
    return finals[-1] if finals else None


def _persisted_handoff(service: InterAgentService, run: Any) -> GeneralistHandoff | None:
    events = service.store.list_recovery_events(
        run.run_id,
        workspace_id=run.workspace_id,
        event_types={"inter_agent.generalist.handoff_prepared"},
    )
    for event in reversed(events):
        if event.event_type != "inter_agent.generalist.handoff_prepared":
            continue
        input_text = str(event.payload.get("input_text") or "").strip()
        analysis_text = str(event.payload.get("analysis_text") or "").strip()
        if input_text and analysis_text:
            return GeneralistHandoff(
                input_text=input_text,
                analysis_text=analysis_text,
                runtime_event_id=str(event.runtime_event_id or "persisted-handoff"),
            )
    return None
