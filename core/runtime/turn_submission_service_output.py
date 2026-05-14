"""Runtime turn submission helpers shared by HTTP and future host surfaces."""

from __future__ import annotations

from dataclasses import replace
import os
from threading import Lock
from typing import TYPE_CHECKING
from uuid import uuid4

from core.providers.service import build_runtime_backend_launch_spec
from core.providers.service import prepare_runtime_skills
from core.runtime.execution_events import RuntimeExecutionEvent
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.service import queue_runtime_turn, record_runtime_event
from core.runtime.thread_catalog_events import mark_thread_user_message_queued, set_thread_availability
from core.runtime.workspace_api_token import register_workspace_api_token
from core.skills.service import list_available_workspace_skills, resolve_runtime_skills

if TYPE_CHECKING:
    from core.api.platform_state import PlatformState
    from core.providers.provider_registry import ProviderRegistry


_SESSION_EXECUTION_LOCKS: dict[str, Lock] = {}
_SESSION_EXECUTION_LOCKS_LOCK = Lock()
_ACTIVE_TURN_STATUSES = {"queued", "active"}


def _queue_turn_with_event(
    state: PlatformState,
    *,
    session: RuntimeSessionRecord,
    input_text: str,
    provider_id: str,
    client_message_id: str | None,
    attachments: list[dict[str, object]] | None,
    app_references: list[dict[str, object]] | None,
) -> tuple[RuntimeTurnRecord, list[RuntimeEventRecord]]:
    turn = queue_runtime_turn(state.runtime_store, turn_id=str(uuid4()), session_id=session.session_id, input_text=input_text)
    payload: dict[str, object] = {"input_text": input_text, "provider_id": provider_id}
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
    mark_thread_user_message_queued(
        state,
        workspace_id=session.workspace_id,
        runtime_session_id=session.session_id,
        input_text=input_text,
        attachments=attachments,
        app_references=app_references,
        now=turn.created_at,
    )
    return turn, [event]

def _record_turn_started(state: PlatformState, *, session_id: str, turn_id: str, provider_id: str) -> RuntimeEventRecord:
    event = record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn_id,
        plane="turn",
        event_type="runtime.turn.started",
        payload={"provider_id": provider_id},
        event_bus=state.runtime_event_bus,
    )
    turn = state.runtime_store.get_turn(turn_id)
    set_thread_availability(
        state,
        workspace_id=turn.workspace_id,
        runtime_session_id=session_id,
        availability="active",
        now=event.created_at,
    )
    return event



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
    if os.environ.get("MAVERICK_RUNTIME_FAKE_RESPONSE") is not None:
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
    token = spec.env_overrides.get("MAVERICK_RUNTIME_API_TOKEN")
    if token:
        register_workspace_api_token(state.runtime_store, token)
    return spec



class _RuntimeTurnOutputRecorder:
    """Persist execution events and track text already emitted as streamed output."""

    def __init__(self, state: PlatformState, *, session_id: str, turn_id: str) -> None:
        self.state = state
        self.session_id = session_id
        self.turn_id = turn_id
        self._streamed_text_parts: list[str] = []

    def record(self, event: RuntimeExecutionEvent) -> RuntimeEventRecord:
        if event.event_type == "runtime.output.delta":
            text = event.payload.get("text")
            if isinstance(text, str) and text:
                self._streamed_text_parts.append(text)
        return _record_execution_event(self.state, session_id=self.session_id, turn_id=self.turn_id, event=event)

    def final_text(self, output_text: str) -> str:
        return _missing_final_suffix(output_text, "".join(self._streamed_text_parts))

    def complete_text(self, output_text: str) -> str:
        return _complete_output_text(output_text, "".join(self._streamed_text_parts))



def _missing_final_suffix(output_text: str, streamed_text: str) -> str:
    if not output_text or not streamed_text:
        return output_text
    if output_text.startswith(streamed_text):
        return output_text[len(streamed_text) :].lstrip()
    prefix_end = _prefix_end_ignoring_whitespace(output_text, streamed_text)
    if prefix_end is not None:
        return output_text[prefix_end:].lstrip()
    if _normalized_text(output_text) == _normalized_text(streamed_text):
        return ""
    return output_text



def _complete_output_text(output_text: str, streamed_text: str) -> str:
    if not streamed_text:
        return output_text
    if not output_text:
        return streamed_text
    if output_text.startswith(streamed_text):
        return output_text
    if _normalized_text(output_text) == _normalized_text(streamed_text):
        return streamed_text
    suffix = _missing_final_suffix(output_text, streamed_text)
    if suffix and suffix != output_text:
        separator = "" if streamed_text.endswith(("\n", " ")) else "\n"
        return f"{streamed_text}{separator}{suffix}"
    return output_text if len(output_text) >= len(streamed_text) else streamed_text



def _prefix_end_ignoring_whitespace(text: str, prefix: str) -> int | None:
    text_index = 0
    prefix_index = 0
    while prefix_index < len(prefix):
        prefix_char = prefix[prefix_index]
        if prefix_char.isspace():
            while prefix_index < len(prefix) and prefix[prefix_index].isspace():
                prefix_index += 1
            if prefix_index >= len(prefix):
                while text_index < len(text) and text[text_index].isspace():
                    text_index += 1
                return text_index
            if text_index >= len(text) or not text[text_index].isspace():
                return None
            while text_index < len(text) and text[text_index].isspace():
                text_index += 1
            continue
        if text_index >= len(text) or text[text_index] != prefix_char:
            return None
        text_index += 1
        prefix_index += 1
    return text_index



def _normalized_text(value: str) -> str:
    return " ".join(value.split())



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
