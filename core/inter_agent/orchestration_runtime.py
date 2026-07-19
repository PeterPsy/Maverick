"""Runtime bridge and generalist steering for orchestrated runs."""

from __future__ import annotations

from typing import Any, Callable

from core.inter_agent.errors import InterAgentOperationError
from core.inter_agent.models import InterAgentParticipantRecord
from core.inter_agent.service import InterAgentService


ParticipantTurnExecutor = Callable[[InterAgentParticipantRecord, str, str], str]
GENERALIST_DIRECTIVE_EVENT_TYPES = {
    "runtime.output.final",
    "runtime.step.updated",
    "runtime.tool_call.completed",
}


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


def sync_generalist_directives(service: InterAgentService, state: Any, run: Any) -> None:
    runtime_store = getattr(state, "runtime_store", None)
    if runtime_store is None or not run.source_runtime_turn_id:
        return
    for event in runtime_store.list_events(run.root_runtime_session_id):
        if event.turn_id != run.source_runtime_turn_id or event.event_type not in GENERALIST_DIRECTIVE_EVENT_TYPES:
            continue
        text = _runtime_event_text(event)
        if not text:
            continue
        service.record_directive(
            workspace_id=run.workspace_id,
            run_id=run.run_id,
            text=text[:6000],
            source_kind="root_generalist",
            source_runtime_event_id=event.event_id,
            source_runtime_turn_id=run.source_runtime_turn_id,
            idempotency_key=f"{run.run_id}:root-directive:{event.event_id}",
        )


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
