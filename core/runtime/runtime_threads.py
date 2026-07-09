"""Core-owned conversation thread lifecycle helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from typing import Callable
from uuid import uuid4

from core.runtime.errors import RuntimeSessionHiddenError, RuntimeSessionNotFoundError, RuntimeThreadNotFoundError
from core.runtime.runtime_session import RuntimeSessionRecord, runtime_session_allows_user_thread
from core.runtime.runtime_thread import RuntimeThreadRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.store import RuntimeStore
from core.runtime.thread_titles import DEFAULT_THREAD_TITLE


RuntimeCleanupCallback = Callable[[str, str], dict[str, object]]


@dataclass(frozen=True)
class _ThreadTurnFacts:
    availability: str
    last_user_message_at: datetime | None
    latest_completed_response: tuple[str, datetime] | None


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


def thread_summary_payload(thread: RuntimeThreadRecord, *, viewer_user_id: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "thread_id": thread.thread_id,
        "runtime_session_id": thread.runtime_session_id,
        "title": thread.title,
        "title_pending": thread.title_pending,
        "agent_label": thread.agent_label,
        "agent_type_id": thread.agent_type_id,
        "agent_role_id": thread.agent_role_id,
        "source_app_id": thread.source_app_id,
        "project_id": thread.project_id,
        "archived": thread.archived,
        "availability": thread.availability,
        "created_at": thread.created_at,
        "updated_at": thread.updated_at,
        "last_user_message_at": thread.last_user_message_at,
        "last_completed_response_at": thread.last_completed_response_at,
    }
    payload["has_unread_completed_response"] = runtime_thread_has_unread_completed_response(
        thread,
        viewer_user_id=viewer_user_id,
    )
    return payload


def thread_detail_payload(thread: RuntimeThreadRecord, *, viewer_user_id: str | None = None) -> dict[str, object]:
    payload = asdict(thread)
    payload.pop("completed_response_read_at_by_user_id", None)
    payload["has_unread_completed_response"] = runtime_thread_has_unread_completed_response(
        thread,
        viewer_user_id=viewer_user_id,
    )
    return payload


def thread_payload(thread: RuntimeThreadRecord, *, viewer_user_id: str | None = None) -> dict[str, object]:
    return thread_detail_payload(thread, viewer_user_id=viewer_user_id)


def thread_recency_key(thread: RuntimeThreadRecord) -> tuple[bool, datetime, datetime, str]:
    user_message_at = thread.last_user_message_at
    return (
        user_message_at is not None,
        user_message_at or thread.created_at,
        thread.created_at,
        thread.thread_id,
    )


def promote_hidden_chat_root_session_with_turns(
    store: RuntimeStore,
    *,
    workspace_id: str,
    runtime_session_id: str,
) -> RuntimeSessionRecord | None:
    """Promote a prepared chat session once it has accepted runtime work.

    Prepared chat sessions are intentionally hidden before first send. If a
    turn exists, the session is no longer only prepared and must be visible in
    the user thread catalog even if an earlier path missed the explicit
    first-send promotion.
    """
    normalized_session_id = runtime_session_id.strip()
    if not normalized_session_id:
        return None
    try:
        session = store.get_session(normalized_session_id)
    except (RuntimeSessionNotFoundError, ValueError):
        return None
    if session.workspace_id != workspace_id:
        return None
    if runtime_session_allows_user_thread(session):
        return session
    if session.session_kind != "chat_root" or session.thread_visibility != "hidden":
        return None
    if not store.list_turns(normalized_session_id):
        return None
    return store.save_session(replace(session, thread_visibility="user", updated_at=utcnow()))


def promote_hidden_chat_root_sessions_with_turns(
    store: RuntimeStore,
    *,
    workspace_id: str,
    runtime_session_ids: Iterable[str] | None = None,
) -> list[RuntimeSessionRecord]:
    promoted: list[RuntimeSessionRecord] = []
    if runtime_session_ids is not None:
        candidates = sorted({str(session_id or "").strip() for session_id in runtime_session_ids})
        candidate_ids = {session_id for session_id in candidates if session_id}
        if not candidate_ids:
            return promoted
        for session in store.list_sessions(workspace_id):
            if (
                session.session_id not in candidate_ids
                or session.session_kind != "chat_root"
                or session.thread_visibility != "hidden"
                or not store.list_turns(session.session_id)
            ):
                continue
            promoted.append(store.save_session(replace(session, thread_visibility="user", updated_at=utcnow())))
        return promoted
    for session in store.list_sessions(workspace_id):
        if session.session_kind != "chat_root" or session.thread_visibility != "hidden":
            continue
        updated = promote_hidden_chat_root_session_with_turns(
            store,
            workspace_id=workspace_id,
            runtime_session_id=session.session_id,
        )
        if updated is not None and runtime_session_allows_user_thread(updated):
            promoted.append(updated)
    return promoted


def list_runtime_threads(store: RuntimeStore, *, workspace_id: str) -> list[RuntimeThreadRecord]:
    stored_threads = store.list_threads(workspace_id)
    promote_hidden_chat_root_sessions_with_turns(
        store,
        workspace_id=workspace_id,
        runtime_session_ids=[thread.runtime_session_id for thread in stored_threads if thread.runtime_session_id],
    )
    threads = _user_visible_runtime_threads(
        store,
        workspace_id=workspace_id,
        threads=stored_threads,
    )
    return sorted(
        threads,
        key=thread_recency_key,
        reverse=True,
    )


def ensure_runtime_threads_for_sessions(
    store: RuntimeStore,
    *,
    workspace_id: str,
    sessions: list[RuntimeSessionRecord],
) -> list[RuntimeThreadRecord]:
    """Ensure every user-visible runtime session in a workspace has one thread."""
    threads = store.list_threads(workspace_id)
    by_thread_id = {thread.thread_id: thread for thread in threads}
    by_session_id = {thread.runtime_session_id: thread for thread in threads if thread.runtime_session_id}
    for session in sessions:
        if (
            session.workspace_id != workspace_id
            or session.session_id in by_session_id
            or not runtime_session_allows_user_thread(session)
        ):
            continue
        thread = create_runtime_thread(
            store,
            workspace_id=workspace_id,
            thread_id=session.session_id,
            runtime_session_id=session.session_id,
            title=DEFAULT_THREAD_TITLE,
            agent_label=session.agent_id,
            source_app_id=session.source_app_id or session.agent_id,
            system_prompt=session.system_prompt or "",
            now=session.started_at or session.updated_at,
        )
        by_session_id[session.session_id] = thread
        by_thread_id[thread.thread_id] = thread
    return sorted(
        _user_visible_runtime_threads(store, workspace_id=workspace_id, threads=list(by_thread_id.values())),
        key=thread_recency_key,
        reverse=True,
    )


def create_runtime_thread(
    store: RuntimeStore,
    *,
    workspace_id: str,
    thread_id: str | None = None,
    runtime_session_id: str = "",
    title: str = "",
    agent_label: str = "",
    agent_type_id: str = "",
    agent_role_id: str = "",
    source_app_id: str = "",
    system_prompt: str = "",
    project_id: str | None = None,
    title_pending: bool = False,
    title_source: str = "",
    title_generation_input_hash: str = "",
    title_generation_failure: str | None = None,
    title_generation_provider_id: str = "",
    title_generation_model_id: str = "",
    turn_facts_known: bool = False,
    availability: str | None = None,
    last_user_message_at: datetime | None = None,
    last_completed_response: tuple[str, datetime] | None = None,
    now: datetime | None = None,
) -> RuntimeThreadRecord:
    normalized_session_id = runtime_session_id.strip()
    if not normalized_session_id:
        raise ValueError("runtime_session_id is required")
    _raise_if_runtime_session_hidden(store, runtime_session_id=normalized_session_id)
    timestamp = now or utcnow()
    known_facts = (
        _ThreadTurnFacts(
            availability=_normalized_thread_availability(str(availability or "free")),
            last_user_message_at=last_user_message_at,
            latest_completed_response=last_completed_response,
        )
        if turn_facts_known
        else None
    )
    existing = find_runtime_thread_by_session(store, workspace_id=workspace_id, runtime_session_id=normalized_session_id)
    if existing is not None:
        patch: dict[str, object] = {"updated_at": timestamp}
        normalized_title_source = _normalized_generated_title_source(title_source)
        normalized_title_hash = title_generation_input_hash.strip()
        latest_user_message_at = (
            known_facts.last_user_message_at
            if known_facts is not None
            else runtime_thread_last_user_message_at_for_session(store, runtime_session_id=normalized_session_id)
        )
        latest_completed_response = (
            known_facts.latest_completed_response
            if known_facts is not None
            else runtime_thread_last_completed_response_for_session(store, runtime_session_id=normalized_session_id)
        )
        if known_facts is not None and existing.availability != known_facts.availability:
            patch["availability"] = known_facts.availability
        if latest_user_message_at is not None and (existing.last_user_message_at is None or existing.last_user_message_at < latest_user_message_at):
            patch["last_user_message_at"] = latest_user_message_at
        if latest_completed_response is not None:
            latest_completed_turn_id, latest_completed_at = latest_completed_response
            if existing.last_completed_response_at is None or existing.last_completed_response_at < latest_completed_at:
                patch["last_completed_response_at"] = latest_completed_at
                patch["last_completed_turn_id"] = latest_completed_turn_id
        if title.strip() and (
            title_pending
            or normalized_title_hash
            or normalized_title_source in {"pending", "ai", "deterministic"}
            or (normalized_title_source == "manual" and not existing.title_pending)
        ):
            patch["title"] = title.strip()[:80]
            patch["title_pending"] = bool(title_pending)
            patch["title_source"] = _thread_title_source(title.strip(), title_source=normalized_title_source, title_pending=title_pending)
            patch["title_generation_input_hash"] = normalized_title_hash
            patch["title_generation_failure"] = title_generation_failure
            patch["title_generation_provider_id"] = title_generation_provider_id.strip()
            patch["title_generation_model_id"] = title_generation_model_id.strip()
        if agent_label.strip():
            patch["agent_label"] = agent_label.strip()[:120]
        if agent_type_id.strip():
            patch["agent_type_id"] = agent_type_id.strip()[:120]
        if agent_role_id.strip():
            patch["agent_role_id"] = agent_role_id.strip()[:120]
        if source_app_id.strip():
            patch["source_app_id"] = source_app_id.strip()[:80]
        if system_prompt.strip():
            patch["system_prompt"] = system_prompt.strip()
        if isinstance(project_id, str) and project_id.strip():
            patch["project_id"] = project_id.strip()
        if len(patch) == 1:
            return existing
        return _save_latest_runtime_thread_patch(store, workspace_id=workspace_id, thread=existing, patch=patch)
    facts = known_facts or _ThreadTurnFacts(
        availability=runtime_thread_availability_for_session(store, runtime_session_id=normalized_session_id),
        last_user_message_at=runtime_thread_last_user_message_at_for_session(store, runtime_session_id=normalized_session_id),
        latest_completed_response=runtime_thread_last_completed_response_for_session(store, runtime_session_id=normalized_session_id),
    )
    thread = RuntimeThreadRecord(
        thread_id=thread_id or normalized_session_id or str(uuid4()),
        workspace_id=workspace_id,
        runtime_session_id=normalized_session_id,
        title=(title.strip() or "New chat")[:80],
        agent_label=agent_label.strip()[:120],
        agent_type_id=agent_type_id.strip()[:120],
        agent_role_id=agent_role_id.strip()[:120],
        source_app_id=source_app_id.strip()[:80],
        system_prompt=system_prompt.strip(),
        project_id=project_id.strip() if isinstance(project_id, str) and project_id.strip() else None,
        archived=False,
        availability=facts.availability,
        created_at=timestamp,
        updated_at=timestamp,
        last_user_message_at=facts.last_user_message_at,
        last_completed_response_at=facts.latest_completed_response[1] if facts.latest_completed_response is not None else None,
        last_completed_turn_id=facts.latest_completed_response[0] if facts.latest_completed_response is not None else None,
        title_pending=bool(title_pending),
        title_source=_thread_title_source(title.strip() or "New chat", title_source=title_source, title_pending=title_pending),
        title_generation_input_hash=title_generation_input_hash.strip(),
        title_generation_failure=title_generation_failure,
        title_generation_provider_id=title_generation_provider_id.strip(),
        title_generation_model_id=title_generation_model_id.strip(),
    )
    return store.save_thread(thread)


def _thread_title_source(title: str, *, title_source: str, title_pending: bool) -> str:
    normalized = _normalized_generated_title_source(title_source)
    if normalized:
        return normalized
    if title_pending:
        return "pending"
    if title.strip() == DEFAULT_THREAD_TITLE:
        return "placeholder"
    return "manual"


def _normalized_generated_title_source(value: str) -> str:
    normalized = str(value or "").strip()
    if normalized in {"placeholder", "pending", "ai", "deterministic", "manual"}:
        return normalized
    return ""


def _thread_title_allows_first_message_generation(thread: RuntimeThreadRecord) -> bool:
    if thread.title.strip() == DEFAULT_THREAD_TITLE:
        return True
    return _normalized_generated_title_source(thread.title_source) == "placeholder"


def _thread_title_allows_initial_ai_generation(
    store: RuntimeStore,
    thread: RuntimeThreadRecord,
    *,
    runtime_session_id: str,
) -> bool:
    if _thread_title_allows_first_message_generation(thread):
        return True
    if _normalized_generated_title_source(thread.title_source) != "deterministic":
        return False
    if thread.title_generation_input_hash or thread.title_generation_failure:
        return False
    return len(store.list_turns(runtime_session_id)) <= 1


def find_runtime_thread_by_session(
    store: RuntimeStore,
    *,
    workspace_id: str,
    runtime_session_id: str,
) -> RuntimeThreadRecord | None:
    normalized_session_id = runtime_session_id.strip()
    if not normalized_session_id:
        return None
    get_by_session = getattr(store, "get_thread_by_runtime_session_id", None)
    if callable(get_by_session):
        thread = get_by_session(workspace_id=workspace_id, runtime_session_id=normalized_session_id)
        if thread is not None and not _runtime_session_is_hidden(store, runtime_session_id=normalized_session_id):
            return thread
        return None
    if _runtime_session_is_hidden(store, runtime_session_id=normalized_session_id):
        return None
    for thread in store.list_threads(workspace_id):
        if thread.runtime_session_id == normalized_session_id:
            return thread
    return None


def update_runtime_thread(
    store: RuntimeStore,
    *,
    thread_id: str,
    workspace_id: str,
    updates: dict[str, object],
    now: datetime | None = None,
) -> RuntimeThreadRecord | None:
    thread = store.get_thread(thread_id)
    if thread.workspace_id != workspace_id:
        return None
    patch: dict[str, object] = {"updated_at": now or utcnow()}
    if "title" in updates:
        title = str(updates.get("title") or "").strip()
        if title:
            patch["title"] = title[:80]
            patch["title_pending"] = False
            patch["title_source"] = "manual"
            patch["title_generation_input_hash"] = ""
            patch["title_generation_failure"] = None
            patch["title_generation_provider_id"] = ""
            patch["title_generation_model_id"] = ""
    for key, limit in {
        "runtime_session_id": 0,
        "agent_label": 120,
        "agent_type_id": 120,
        "agent_role_id": 120,
        "source_app_id": 80,
        "system_prompt": 0,
    }.items():
        if key not in updates:
            continue
        value = str(updates.get(key) or "").strip()
        if key == "runtime_session_id" and value:
            _raise_if_runtime_session_hidden(store, runtime_session_id=value)
        patch[key] = value[:limit] if limit else value
    if "project_id" in updates:
        project_id = str(updates.get("project_id") or "").strip()
        patch["project_id"] = project_id or None
    if "archived" in updates:
        patch["archived"] = bool(updates.get("archived"))
    if len(patch) == 1:
        return thread
    return store.save_thread(replace(thread, **patch))


def reconcile_runtime_thread_availability(
    store: RuntimeStore,
    *,
    workspace_id: str,
    thread: RuntimeThreadRecord,
    now: datetime | None = None,
) -> RuntimeThreadRecord:
    if thread.workspace_id != workspace_id or not thread.runtime_session_id:
        return thread
    return _reconcile_runtime_thread_with_facts(
        store,
        workspace_id=workspace_id,
        thread=thread,
        facts=_turn_facts_for_session(store.list_turns(thread.runtime_session_id)),
        now=now,
    )


def _reconcile_runtime_thread_with_facts(
    store: RuntimeStore,
    *,
    workspace_id: str,
    thread: RuntimeThreadRecord,
    facts: _ThreadTurnFacts | None,
    now: datetime | None = None,
) -> RuntimeThreadRecord:
    if thread.workspace_id != workspace_id or not thread.runtime_session_id:
        return thread
    facts = facts or _ThreadTurnFacts(availability="free", last_user_message_at=None, latest_completed_response=None)
    expected_availability = facts.availability
    expected_last_user_message_at = facts.last_user_message_at
    expected_completed_response = facts.latest_completed_response
    patch: dict[str, object] = {}
    if thread.availability != expected_availability:
        patch["availability"] = expected_availability
    if expected_last_user_message_at is not None and (
        thread.last_user_message_at is None or thread.last_user_message_at < expected_last_user_message_at
    ):
        patch["last_user_message_at"] = expected_last_user_message_at
    if expected_completed_response is not None:
        expected_completed_turn_id, expected_completed_at = expected_completed_response
        if thread.last_completed_response_at is None or thread.last_completed_response_at < expected_completed_at:
            patch["last_completed_response_at"] = expected_completed_at
            patch["last_completed_turn_id"] = expected_completed_turn_id
    if not patch:
        return thread
    patch["updated_at"] = now or utcnow()
    return _save_latest_runtime_thread_patch(store, workspace_id=workspace_id, thread=thread, patch=patch)


def _user_visible_runtime_threads(
    store: RuntimeStore,
    *,
    workspace_id: str,
    threads: list[RuntimeThreadRecord],
) -> list[RuntimeThreadRecord]:
    visibility_map = _runtime_session_thread_visibility_map(store, workspace_id=workspace_id)
    if visibility_map is not None:
        return [thread for thread in threads if not thread.runtime_session_id or visibility_map.get(thread.runtime_session_id, True)]
    hidden_session_ids = {session.session_id for session in store.list_sessions(workspace_id) if not runtime_session_allows_user_thread(session)}
    return [
        thread
        for thread in threads
        if not thread.runtime_session_id
        or (
            thread.runtime_session_id not in hidden_session_ids
            and not _runtime_session_is_hidden(store, runtime_session_id=thread.runtime_session_id)
        )
    ]


def _runtime_session_thread_visibility_map(store: RuntimeStore, *, workspace_id: str) -> dict[str, bool] | None:
    visibility_map = getattr(store, "runtime_session_thread_visibility_map", None)
    if not callable(visibility_map):
        return None
    return dict(visibility_map(workspace_id))


def _runtime_session_is_hidden(store: RuntimeStore, *, runtime_session_id: str) -> bool:
    try:
        session = store.get_session(runtime_session_id)
    except RuntimeSessionNotFoundError:
        return False
    except ValueError:
        return True
    promoted = promote_hidden_chat_root_session_with_turns(
        store,
        workspace_id=session.workspace_id,
        runtime_session_id=runtime_session_id,
    )
    if promoted is not None:
        session = promoted
    return not runtime_session_allows_user_thread(session)


def _raise_if_runtime_session_hidden(store: RuntimeStore, *, runtime_session_id: str) -> None:
    if _runtime_session_is_hidden(store, runtime_session_id=runtime_session_id):
        raise RuntimeSessionHiddenError(
            f"Runtime session `{runtime_session_id}` is hidden and cannot be represented by a runtime thread."
        )


def _turn_facts_for_session(turns: list[RuntimeTurnRecord]) -> _ThreadTurnFacts:
    if not turns:
        return _ThreadTurnFacts(availability="free", last_user_message_at=None, latest_completed_response=None)
    statuses = {turn.status for turn in turns}
    if "active" in statuses:
        availability = "active"
    elif "queued" in statuses:
        availability = "queued"
    else:
        availability = "free"
    completed_turns = [turn for turn in turns if turn.status == "completed"]
    latest_completed_response: tuple[str, datetime] | None = None
    if completed_turns:
        latest = max(completed_turns, key=lambda turn: turn.completed_at or turn.updated_at)
        latest_completed_response = (latest.turn_id, latest.completed_at or latest.updated_at)
    return _ThreadTurnFacts(
        availability=availability,
        last_user_message_at=max(turn.created_at for turn in turns),
        latest_completed_response=latest_completed_response,
    )


def runtime_thread_availability_for_session(store: RuntimeStore, *, runtime_session_id: str) -> str:
    has_turn_with_status = getattr(store, "has_turn_with_status", None)
    if callable(has_turn_with_status):
        if has_turn_with_status(runtime_session_id, {"active"}):
            return "active"
        if has_turn_with_status(runtime_session_id, {"queued"}):
            return "queued"
        return "free"
    statuses = {turn.status for turn in store.list_turns(runtime_session_id)}
    if "active" in statuses:
        return "active"
    if "queued" in statuses:
        return "queued"
    return "free"


def runtime_thread_last_user_message_at_for_session(store: RuntimeStore, *, runtime_session_id: str) -> datetime | None:
    turns = store.list_turns(runtime_session_id)
    if not turns:
        return None
    return max(turn.created_at for turn in turns)


def runtime_thread_last_completed_response_for_session(store: RuntimeStore, *, runtime_session_id: str) -> tuple[str, datetime] | None:
    completed_turns = [turn for turn in store.list_turns(runtime_session_id) if turn.status == "completed"]
    if not completed_turns:
        return None
    latest = max(completed_turns, key=lambda turn: turn.completed_at or turn.updated_at)
    return latest.turn_id, latest.completed_at or latest.updated_at


def mark_runtime_thread_user_message(
    store: RuntimeStore,
    *,
    workspace_id: str,
    runtime_session_id: str,
    input_text: object = "",
    attachments: Iterable[Mapping[str, object]] | None = None,
    app_references: Iterable[Mapping[str, object]] | None = None,
    title_generation_input_hash: str = "",
    availability: str | None = None,
    now: datetime | None = None,
) -> RuntimeThreadRecord | None:
    thread = find_runtime_thread_by_session(store, workspace_id=workspace_id, runtime_session_id=runtime_session_id)
    if thread is None:
        return None
    timestamp = now or utcnow()
    patch: dict[str, object] = {
        "availability": _known_or_current_thread_availability(store, runtime_session_id=runtime_session_id, availability=availability),
        "last_user_message_at": timestamp,
        "updated_at": timestamp,
    }
    if thread.title_pending:
        pass
    elif _thread_title_allows_initial_ai_generation(store, thread, runtime_session_id=runtime_session_id):
        pending_hash = title_generation_input_hash.strip()
        if pending_hash:
            patch["title"] = DEFAULT_THREAD_TITLE
            patch["title_pending"] = True
            patch["title_source"] = "pending"
            patch["title_generation_input_hash"] = pending_hash
            patch["title_generation_failure"] = None
            patch["title_generation_provider_id"] = ""
            patch["title_generation_model_id"] = ""
    return store.save_thread(replace(thread, **patch))


def complete_runtime_thread_title_generation(
    store: RuntimeStore,
    *,
    workspace_id: str,
    runtime_session_id: str,
    title_generation_input_hash: str,
    title: str,
    title_source: str,
    failure: str | None = None,
    title_generation_provider_id: str = "",
    title_generation_model_id: str = "",
    now: datetime | None = None,
) -> RuntimeThreadRecord | None:
    thread = find_runtime_thread_by_session(store, workspace_id=workspace_id, runtime_session_id=runtime_session_id)
    if thread is None:
        return None
    if not thread.title_pending:
        return None
    expected_hash = title_generation_input_hash.strip()
    if thread.title_generation_input_hash and thread.title_generation_input_hash != expected_hash:
        return None
    clean_title = str(title or "").strip()
    if not clean_title:
        clean_title = DEFAULT_THREAD_TITLE
    timestamp = now or utcnow()
    return store.save_thread(
        replace(
            thread,
            title=clean_title[:80],
            title_pending=False,
            title_source=_normalized_generated_title_source(title_source),
            title_generation_failure=failure,
            title_generation_provider_id=title_generation_provider_id.strip(),
            title_generation_model_id=title_generation_model_id.strip(),
            updated_at=timestamp,
        )
    )


def mark_runtime_thread_response_completed(
    store: RuntimeStore,
    *,
    workspace_id: str,
    runtime_session_id: str,
    turn_id: str,
    availability: str | None = None,
    now: datetime | None = None,
) -> RuntimeThreadRecord | None:
    thread = find_runtime_thread_by_session(store, workspace_id=workspace_id, runtime_session_id=runtime_session_id)
    if thread is None:
        return None
    timestamp = now or utcnow()
    patch: dict[str, object] = {
        "availability": _known_or_current_thread_availability(store, runtime_session_id=runtime_session_id, availability=availability),
        "updated_at": timestamp,
    }
    if thread.last_completed_response_at is None or thread.last_completed_response_at <= timestamp:
        patch["last_completed_response_at"] = timestamp
        patch["last_completed_turn_id"] = turn_id
    return _save_latest_runtime_thread_patch(store, workspace_id=workspace_id, thread=thread, patch=patch)


def mark_runtime_thread_completed_response_read(
    store: RuntimeStore,
    *,
    thread_id: str,
    workspace_id: str,
    user_id: str,
    now: datetime | None = None,
) -> RuntimeThreadRecord | None:
    normalized_user_id = user_id.strip()
    if not normalized_user_id:
        raise ValueError("user_id is required")
    thread = store.get_thread(thread_id)
    if thread.workspace_id != workspace_id:
        return None
    timestamp = now or utcnow()
    receipts = dict(thread.completed_response_read_at_by_user_id or {})
    if receipts.get(normalized_user_id) == timestamp:
        return thread
    receipts[normalized_user_id] = timestamp
    return _save_latest_runtime_thread_patch(
        store,
        workspace_id=workspace_id,
        thread=thread,
        patch={
            "completed_response_read_at_by_user_id": receipts,
            "updated_at": timestamp,
        },
    )


def runtime_thread_has_unread_completed_response(thread: RuntimeThreadRecord, *, viewer_user_id: str | None) -> bool:
    normalized_user_id = str(viewer_user_id or "").strip()
    if not normalized_user_id or thread.last_completed_response_at is None:
        return False
    read_at = (thread.completed_response_read_at_by_user_id or {}).get(normalized_user_id)
    return read_at is None or read_at < thread.last_completed_response_at


def update_runtime_thread_availability(
    store: RuntimeStore,
    *,
    workspace_id: str,
    runtime_session_id: str,
    availability: str,
    now: datetime | None = None,
) -> RuntimeThreadRecord | None:
    thread = find_runtime_thread_by_session(store, workspace_id=workspace_id, runtime_session_id=runtime_session_id)
    if thread is None:
        return None
    value = _normalized_thread_availability(availability)
    if not value or thread.availability == value:
        return thread
    timestamp = now or utcnow()
    return _save_latest_runtime_thread_patch(
        store,
        workspace_id=workspace_id,
        thread=thread,
        patch={"availability": value, "updated_at": timestamp},
    )


def _known_or_current_thread_availability(store: RuntimeStore, *, runtime_session_id: str, availability: str | None) -> str:
    if availability is None:
        return runtime_thread_availability_for_session(store, runtime_session_id=runtime_session_id)
    value = _normalized_thread_availability(str(availability))
    if value == "active":
        return value
    current = runtime_thread_availability_for_session(store, runtime_session_id=runtime_session_id)
    if value == "queued" and current == "active":
        return current
    if value == "free" and current != "free":
        return current
    return value


def _save_latest_runtime_thread_patch(
    store: RuntimeStore,
    *,
    workspace_id: str,
    thread: RuntimeThreadRecord,
    patch: dict[str, object],
) -> RuntimeThreadRecord:
    """Apply a partial thread patch to the freshest stored record."""
    if not patch:
        return thread
    try:
        latest = store.get_thread(thread.thread_id)
    except RuntimeThreadNotFoundError:
        return thread
    if latest.workspace_id != workspace_id:
        return thread
    clean_patch = _runtime_thread_patch_for_latest(latest, patch)
    if not clean_patch:
        return latest
    return store.save_thread(replace(latest, **clean_patch))


def _runtime_thread_patch_for_latest(thread: RuntimeThreadRecord, patch: dict[str, object]) -> dict[str, object]:
    clean_patch = dict(patch)
    _drop_stale_datetime_patch(clean_patch, "last_user_message_at", thread.last_user_message_at)
    _drop_stale_datetime_patch(clean_patch, "updated_at", thread.updated_at)
    if _drop_stale_datetime_patch(clean_patch, "last_completed_response_at", thread.last_completed_response_at):
        clean_patch.pop("last_completed_turn_id", None)
    if "completed_response_read_at_by_user_id" in clean_patch:
        clean_patch["completed_response_read_at_by_user_id"] = _merged_completed_response_receipts(
            thread.completed_response_read_at_by_user_id,
            clean_patch["completed_response_read_at_by_user_id"],
        )
    return clean_patch


def _drop_stale_datetime_patch(patch: dict[str, object], key: str, current: datetime | None) -> bool:
    if key not in patch:
        return False
    value = patch.get(key)
    if not isinstance(value, datetime):
        patch.pop(key, None)
        return True
    if current is not None and current > value:
        patch.pop(key, None)
        return True
    return False


def _merged_completed_response_receipts(current: dict[str, datetime] | None, value: object) -> dict[str, datetime]:
    merged = dict(current or {})
    if not isinstance(value, dict):
        return merged
    for user_id, read_at in value.items():
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id or not isinstance(read_at, datetime):
            continue
        existing = merged.get(normalized_user_id)
        if existing is not None and existing > read_at:
            continue
        merged[normalized_user_id] = read_at
    return merged


def _normalized_thread_availability(value: str) -> str:
    normalized = value.strip()
    if normalized not in {"free", "queued", "active"}:
        raise ValueError(f"Unsupported runtime thread availability `{normalized}`.")
    return normalized


def delete_runtime_thread_complete(
    store: RuntimeStore,
    *,
    thread_id: str,
    workspace_id: str,
    cleanup_runtime: RuntimeCleanupCallback,
    reason: str = "runtime_thread_deleted",
) -> tuple[RuntimeThreadRecord | None, dict[str, object] | None]:
    thread = store.get_thread(thread_id)
    if thread.workspace_id != workspace_id:
        return None, None
    cleanup = cleanup_runtime(thread.runtime_session_id, reason) if thread.runtime_session_id else None
    store.delete_thread(thread.thread_id)
    return thread, cleanup


def clear_runtime_threads_complete(
    store: RuntimeStore,
    *,
    workspace_id: str,
    cleanup_runtime: RuntimeCleanupCallback,
    reason: str = "runtime_threads_cleared",
) -> tuple[list[RuntimeThreadRecord], list[dict[str, object]]]:
    threads = list_runtime_threads(store, workspace_id=workspace_id)
    cleanups: list[dict[str, object]] = []
    for thread in threads:
        if thread.runtime_session_id:
            cleanups.append(cleanup_runtime(thread.runtime_session_id, reason))
        store.delete_thread(thread.thread_id)
    return threads, cleanups
