"""Idempotent acquisition and bounded classification for prepared chat sessions."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
import fcntl
from hashlib import sha256
from pathlib import Path
from threading import Lock, RLock
from typing import Iterator

from core.runtime.errors import RuntimeSessionNotFoundError
from core.runtime.prepared_session_config import (
    stored_prepared_session_configuration_key,
)
from core.runtime.runtime_session import RuntimeSessionRecord
from core.workspaces.paths import workspace_root


PREPARED_SESSION_TTL_SECONDS = 30 * 60
PREPARED_SESSION_POOL_MAX_PER_OWNER = 2
@dataclass
class _PreparedOwnerLockEntry:
    lock: RLock
    users: int = 0


_PREPARED_SESSION_LOCKS_GUARD = Lock()
_PREPARED_SESSION_OWNER_LOCKS: dict[tuple[str, str, str], _PreparedOwnerLockEntry] = {}


@dataclass(frozen=True)
class PreparedSessionAcquisition:
    """The stable prepared session selected for one configuration request."""

    session: RuntimeSessionRecord
    reused: bool


@dataclass(frozen=True)
class PreparedSessionCleanupCandidate:
    """One still-hidden session selected for official runtime cleanup."""

    session_id: str
    reason: str
    updated_at: datetime


def acquire_prepared_session(
    state,
    *,
    workspace_id: str,
    owner_user_id: str,
    fingerprint: str,
    create: Callable[[], RuntimeSessionRecord],
    now: datetime | None = None,
) -> PreparedSessionAcquisition:
    """Return one prepared aggregate for a workspace/user/configuration key.

    The process lock protects threaded in-process hosts. The workspace lock also
    makes the find-or-create section single-flight if multiple host processes
    share the same runtime store.
    """
    requested_at = now or datetime.now(tz=UTC)
    with _prepared_owner_singleflight(
        repository_root=state.repository_root,
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
    ):
        existing = _find_reusable_prepared_session(
            state,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            fingerprint=fingerprint,
        )
        if existing is not None:
            with state.runtime_store.session_lifecycle_handoff(
                workspace_id=workspace_id,
                session_id=existing.session_id,
            ):
                try:
                    current = state.runtime_store.get_session(existing.session_id)
                except RuntimeSessionNotFoundError:
                    current = None
                if current is not None and _is_reusable_prepared_session(
                    state,
                    current,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    fingerprint=fingerprint,
                ):
                    touched = state.runtime_store.save_session(
                        replace(current, updated_at=requested_at)
                    )
                    return PreparedSessionAcquisition(session=touched, reused=True)
        created = create()
        if created.prepared_session_fingerprint != fingerprint:
            raise ValueError("Prepared session factory returned a different fingerprint.")
        return PreparedSessionAcquisition(session=created, reused=False)


def prepared_session_cleanup_candidates(
    state,
    *,
    now: datetime | None = None,
    ttl_seconds: float = PREPARED_SESSION_TTL_SECONDS,
    max_per_owner: int = PREPARED_SESSION_POOL_MAX_PER_OWNER,
) -> list[PreparedSessionCleanupCandidate]:
    """Select expired, duplicate, and over-limit hidden Chat roots only."""
    if max_per_owner < 1:
        raise ValueError("Prepared session pool limit must be positive.")
    current_time = now or datetime.now(tz=UTC)
    cutoff = current_time - timedelta(seconds=max(0.0, ttl_seconds))
    eligible = [
        session
        for session in state.runtime_store.list_all_sessions()
        if _is_cleanup_eligible_prepared_session(state, session)
    ]
    reasons: dict[str, str] = {}
    for session in eligible:
        if session.updated_at < cutoff:
            reasons[session.session_id] = "prepared_session_expired"

    by_configuration: dict[tuple[str, str, str], list[RuntimeSessionRecord]] = {}
    for session in eligible:
        if session.session_id in reasons:
            continue
        key = (
            session.workspace_id,
            session.owner_user_id or "",
            stored_prepared_session_configuration_key(session),
        )
        by_configuration.setdefault(key, []).append(session)
    for sessions in by_configuration.values():
        for duplicate in _newest_first(sessions)[1:]:
            reasons[duplicate.session_id] = "prepared_session_duplicate"

    by_owner: dict[tuple[str, str], list[RuntimeSessionRecord]] = {}
    for session in eligible:
        if session.session_id in reasons:
            continue
        by_owner.setdefault(
            (session.workspace_id, session.owner_user_id or ""),
            [],
        ).append(session)
    for sessions in by_owner.values():
        for overflow in _newest_first(sessions)[max_per_owner:]:
            reasons[overflow.session_id] = "prepared_session_pool_limit"

    priority = {
        "prepared_session_expired": 0,
        "prepared_session_duplicate": 1,
        "prepared_session_pool_limit": 2,
    }
    candidates = [
        PreparedSessionCleanupCandidate(
            session_id=session.session_id,
            reason=reasons[session.session_id],
            updated_at=session.updated_at,
        )
        for session in eligible
        if session.session_id in reasons
    ]
    return sorted(
        candidates,
        key=lambda candidate: (
            priority[candidate.reason],
            candidate.updated_at,
            candidate.session_id,
        ),
    )


def _find_reusable_prepared_session(
    state,
    *,
    workspace_id: str,
    owner_user_id: str,
    fingerprint: str,
) -> RuntimeSessionRecord | None:
    candidates = [
        session
        for session in state.runtime_store.list_sessions(workspace_id)
        if _is_reusable_prepared_session(
            state,
            session,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            fingerprint=fingerprint,
        )
    ]
    ordered = _newest_first(candidates)
    return ordered[0] if ordered else None


def _is_reusable_prepared_session(
    state,
    session: RuntimeSessionRecord,
    *,
    workspace_id: str,
    owner_user_id: str,
    fingerprint: str,
) -> bool:
    return (
        session.workspace_id == workspace_id
        and session.owner_user_id == owner_user_id
        and session.session_kind == "chat_root"
        and session.thread_visibility == "hidden"
        and session.preparation_status == "prepared"
        and session.status in {"created", "running"}
        and session.prepared_session_fingerprint == fingerprint
        and not state.runtime_store.list_turns(session.session_id)
    )


def _is_cleanup_eligible_prepared_session(state, session: RuntimeSessionRecord) -> bool:
    if (
        session.session_kind != "chat_root"
        or session.thread_visibility != "hidden"
        or not session.owner_user_id
    ):
        return False
    if session.prepared_session_fingerprint is None and session.source_app_id != "chat":
        return False
    return not state.runtime_store.list_turns(session.session_id)


@contextmanager
def _prepared_owner_singleflight(
    *,
    repository_root: Path,
    workspace_id: str,
    owner_user_id: str,
) -> Iterator[None]:
    key = (str(repository_root.resolve()), workspace_id, owner_user_id)
    with _PREPARED_SESSION_LOCKS_GUARD:
        entry = _PREPARED_SESSION_OWNER_LOCKS.get(key)
        if entry is None:
            entry = _PreparedOwnerLockEntry(lock=RLock())
            _PREPARED_SESSION_OWNER_LOCKS[key] = entry
        entry.users += 1
    owner_digest = sha256(owner_user_id.encode("utf-8")).hexdigest()[:24]
    lock_root = (
        workspace_root(workspace_id, start_path=repository_root)
        / "runtime"
        / ".prepared-session-pool"
    )
    lock_root.mkdir(parents=True, exist_ok=True)
    lock_path = lock_root / f"{owner_digest}.lock"
    try:
        with entry.lock:
            with lock_path.open("a+b") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        with _PREPARED_SESSION_LOCKS_GUARD:
            entry.users -= 1
            if entry.users == 0 and _PREPARED_SESSION_OWNER_LOCKS.get(key) is entry:
                _PREPARED_SESSION_OWNER_LOCKS.pop(key, None)


def _newest_first(sessions: list[RuntimeSessionRecord]) -> list[RuntimeSessionRecord]:
    return sorted(
        sessions,
        key=lambda session: (session.updated_at, session.session_id),
        reverse=True,
    )
