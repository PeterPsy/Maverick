"""Runtime thread title derivation helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING

from core.runtime.thread_title_generation import (
    DEFAULT_THREAD_TITLE,
    MAX_THREAD_TITLE_CHARS,
    MAX_THREAD_TITLE_WORDS,
    derive_thread_title,
    normalized_title_input,
)

if TYPE_CHECKING:
    from core.runtime.runtime_events import RuntimeEventRecord
    from core.runtime.runtime_session import RuntimeSessionRecord
    from core.runtime.runtime_turns import RuntimeTurnRecord
    from core.runtime.store import RuntimeStore


def runtime_thread_title_for_session(
    store: RuntimeStore,
    session: RuntimeSessionRecord,
    *,
    input_text: object = "",
    attachments: Iterable[Mapping[str, object]] | None = None,
    app_references: Iterable[Mapping[str, object]] | None = None,
) -> str:
    """Return the best available title for a runtime session."""
    title = derive_thread_title(input_text, attachments=attachments, app_references=app_references)
    if title != DEFAULT_THREAD_TITLE:
        return title
    stored_title = _title_from_stored_turns(store, session.session_id)
    if stored_title != DEFAULT_THREAD_TITLE:
        return stored_title
    agent_title = str(session.agent_id or "").strip()
    return _bounded_title(agent_title) or DEFAULT_THREAD_TITLE


def runtime_thread_title_for_user_message(
    store: RuntimeStore,
    runtime_session_id: str,
    *,
    input_text: object = "",
    attachments: Iterable[Mapping[str, object]] | None = None,
    app_references: Iterable[Mapping[str, object]] | None = None,
) -> str:
    input_key = normalized_title_input(input_text)
    direct_title = derive_thread_title(input_text, attachments=attachments, app_references=app_references)
    return _title_from_stored_turns(
        store,
        runtime_session_id,
        input_key=input_key,
        direct_title=direct_title,
    )


def _title_from_stored_turns(
    store: RuntimeStore,
    runtime_session_id: str,
    *,
    input_key: str = "",
    direct_title: str = DEFAULT_THREAD_TITLE,
) -> str:
    events_by_turn_id = _queued_events_by_turn_id(store, runtime_session_id)
    for turn in _stored_turns_by_created_at(store, runtime_session_id):
        event = events_by_turn_id.get(turn.turn_id)
        event_payload = event.payload if event is not None and isinstance(event.payload, Mapping) else {}
        title_input = event_payload.get("input_text") or turn.input_text or ""
        title = derive_thread_title(
            title_input,
            attachments=_mapping_items(event_payload.get("attachments")),
            app_references=_mapping_items(event_payload.get("app_references")),
        )
        if title == DEFAULT_THREAD_TITLE:
            continue
        if direct_title != DEFAULT_THREAD_TITLE and input_key and input_key == normalized_title_input(title_input):
            return direct_title
        return title
    if direct_title != DEFAULT_THREAD_TITLE:
        return direct_title
    return DEFAULT_THREAD_TITLE


def _stored_turns_by_created_at(store: RuntimeStore, runtime_session_id: str) -> list[RuntimeTurnRecord]:
    return sorted(store.list_turns(runtime_session_id), key=lambda item: item.created_at)


def _queued_events_by_turn_id(store: RuntimeStore, runtime_session_id: str) -> dict[str, RuntimeEventRecord]:
    events_by_turn_id: dict[str, RuntimeEventRecord] = {}
    for event in sorted(store.list_events(runtime_session_id), key=lambda item: item.created_at):
        if event.event_type != "runtime.turn.queued" or not event.turn_id:
            continue
        events_by_turn_id.setdefault(event.turn_id, event)
    return events_by_turn_id


def _mapping_items(value: object) -> list[Mapping[str, object]] | None:
    if not isinstance(value, list):
        return None
    return [item for item in value if isinstance(item, Mapping)]


def _bounded_title(value: str) -> str:
    title = " ".join(str(value or "").split()).strip()
    if len(title) <= MAX_THREAD_TITLE_CHARS:
        return title
    bounded = title[:MAX_THREAD_TITLE_CHARS].rsplit(" ", 1)[0].strip()
    return bounded or title[:MAX_THREAD_TITLE_CHARS].strip()


__all__ = [
    "DEFAULT_THREAD_TITLE",
    "MAX_THREAD_TITLE_CHARS",
    "MAX_THREAD_TITLE_WORDS",
    "derive_thread_title",
    "runtime_thread_title_for_session",
    "runtime_thread_title_for_user_message",
]
