"""Local handles backed by durable cancellation fences for hosted requests."""

from __future__ import annotations

from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import socket
from threading import Event, Lock, Thread
import time
from typing import TYPE_CHECKING, Iterator
from uuid import uuid4

from core.providers.text_generation import HostedTextCancellation
from core.runtime.errors import RuntimeTurnNotFoundError

if TYPE_CHECKING:
    from core.runtime.store import RuntimeStore


_ACTIVE_REQUESTS: dict[tuple[str, str | None], HostedTextCancellation] = {}
_ACTIVE_REQUESTS_LOCK = Lock()
_CANCELLATION_POLL_SECONDS = 0.025
_TERMINATION_WAIT_SECONDS = 5.0
_PROCESS_GENERATION = uuid4().hex


@dataclass(frozen=True)
class _PlainHostedProcessOwner:
    owner_id: str
    owner_kind: str
    host_id: str
    pid: int
    process_start: str


@dataclass(frozen=True)
class _PlainHostedRequestLease:
    turn_id: str
    generation: str
    started_at: datetime


def plain_hosted_request_owner_id() -> str:
    """Return the stable identity for this backend process incarnation."""
    return _current_process_owner().owner_id


def reconcile_stale_plain_hosted_request_owners(
    store: "RuntimeStore",
    *,
    session_id: str | None = None,
) -> int:
    """Close exact leases only after their local process owner is proven dead."""
    session_ids = (
        [session_id]
        if session_id is not None
        else [session.session_id for session in store.list_all_sessions()]
    )
    reconciled = 0
    for candidate_session_id in session_ids:
        for turn in store.list_turns(candidate_session_id):
            if turn.provider_request_started_at is None or turn.provider_request_finished_at is not None:
                continue
            if _provider_request_owner_is_alive(turn):
                continue
            _persisted, applied = store.reconcile_turn_provider_request_if_current(
                turn_id=turn.turn_id,
                expected_owner_id=turn.provider_request_owner_id,
                expected_generation=turn.provider_request_generation,
                expected_started_at=turn.provider_request_started_at,
            )
            reconciled += int(applied)
    return reconciled


@contextmanager
def plain_hosted_request_cancellation(
    *,
    session_id: str,
    turn_id: str | None,
    store: "RuntimeStore | None" = None,
) -> Iterator[HostedTextCancellation]:
    """Register one request and watch its durable turn fence until it unwinds."""
    key = (session_id, turn_id)
    cancellation = HostedTextCancellation()
    monitor_stop = Event()
    monitor: Thread | None = None
    owner_id: str | None = None
    request_generation: str | None = None
    durable_lease_started = False
    with _ACTIVE_REQUESTS_LOCK:
        if key in _ACTIVE_REQUESTS:
            raise RuntimeError(f"Plain-hosted provider request `{turn_id or session_id}` is already active.")
        _ACTIVE_REQUESTS[key] = cancellation
    try:
        if store is not None and turn_id is not None:
            owner = _current_process_owner()
            owner_id = owner.owner_id
            request_generation = uuid4().hex
            tracked = store.mark_turn_provider_request_started(
                turn_id=turn_id,
                owner_id=owner_id,
                generation=request_generation,
                owner_kind=owner.owner_kind,
                owner_host_id=owner.host_id,
                owner_pid=owner.pid,
                owner_process_start=owner.process_start,
            )
            durable_lease_started = True
            if tracked.cancellation_requested_at is not None or tracked.status == "cancelled":
                cancellation.cancel()
            monitor = Thread(
                target=_watch_durable_cancellation,
                kwargs={
                    "store": store,
                    "turn_id": turn_id,
                    "cancellation": cancellation,
                    "stop": monitor_stop,
                },
                name=f"maverick-hosted-cancel-{turn_id}",
                daemon=True,
            )
            monitor.start()
        yield cancellation
    finally:
        monitor_stop.set()
        cancellation.mark_finished()
        with _ACTIVE_REQUESTS_LOCK:
            if _ACTIVE_REQUESTS.get(key) is cancellation:
                _ACTIVE_REQUESTS.pop(key, None)
        if monitor is not None:
            monitor.join(timeout=max(0.1, _CANCELLATION_POLL_SECONDS * 4))
        if (
            store is not None
            and turn_id is not None
            and owner_id is not None
            and request_generation is not None
            and durable_lease_started
        ):
            with suppress(Exception):
                store.mark_turn_provider_request_finished(
                    turn_id=turn_id,
                    owner_id=owner_id,
                    generation=request_generation,
                    cancellation_observed=cancellation.cancelled,
                )


def interrupt_plain_hosted_requests(
    session_id: str,
    *,
    turn_id: str | None = None,
    store: "RuntimeStore | None" = None,
    wait_for_termination: bool = False,
) -> bool:
    """Cancel and await only the hosted request incarnation observed for one turn."""
    with _ACTIVE_REQUESTS_LOCK:
        cancellations = [
            cancellation
            for (active_session_id, active_turn_id), cancellation in _ACTIVE_REQUESTS.items()
            if active_session_id == session_id
            and (turn_id is None or active_turn_id == turn_id)
        ]
    for cancellation in cancellations:
        cancellation.cancel()
    if store is not None:
        reconcile_stale_plain_hosted_request_owners(store, session_id=session_id)
    lease = _durable_provider_request_lease(store, session_id=session_id, turn_id=turn_id)
    remote_active = _durable_provider_request_inflight(store, lease=lease)
    if wait_for_termination:
        deadline = time.monotonic() + _TERMINATION_WAIT_SECONDS
        unfinished_local = False
        for cancellation in cancellations:
            if not cancellation.wait_finished(timeout=max(0.0, deadline - time.monotonic())):
                unfinished_local = True
        while remote_active and time.monotonic() < deadline:
            time.sleep(_CANCELLATION_POLL_SECONDS)
            if store is not None:
                reconcile_stale_plain_hosted_request_owners(store, session_id=session_id)
            remote_active = _durable_provider_request_inflight(store, lease=lease)
        if unfinished_local or remote_active:
            raise TimeoutError(
                f"Plain-hosted provider request for runtime session `{session_id}` did not stop after cancellation."
            )
    remote_request_acknowledged = _durable_provider_request_acknowledged(store, lease=lease)
    return bool(cancellations or remote_request_acknowledged)


def _watch_durable_cancellation(
    *,
    store: "RuntimeStore",
    turn_id: str,
    cancellation: HostedTextCancellation,
    stop: Event,
) -> None:
    while not stop.is_set():
        try:
            turn = store.get_turn(turn_id)
        except RuntimeTurnNotFoundError:
            cancellation.cancel()
            return
        except Exception:
            if stop.wait(_CANCELLATION_POLL_SECONDS):
                return
            continue
        if turn.cancellation_requested_at is not None or turn.status == "cancelled":
            cancellation.cancel()
            return
        stop.wait(_CANCELLATION_POLL_SECONDS)


def _durable_provider_request_lease(
    store: "RuntimeStore | None",
    *,
    session_id: str,
    turn_id: str | None,
) -> _PlainHostedRequestLease | None:
    if store is None or turn_id is None:
        return None
    try:
        turn = store.get_turn(turn_id)
    except RuntimeTurnNotFoundError:
        return None
    generation = (turn.provider_request_generation or "").strip()
    if turn.session_id != session_id or turn.provider_request_started_at is None or not generation:
        return None
    return _PlainHostedRequestLease(
        turn_id=turn.turn_id,
        generation=generation,
        started_at=turn.provider_request_started_at,
    )


def _durable_provider_request_inflight(
    store: "RuntimeStore | None",
    *,
    lease: _PlainHostedRequestLease | None,
) -> bool:
    turn = _turn_for_exact_lease(store, lease=lease)
    return bool(
        turn is not None
        and turn.cancellation_requested_at is not None
        and turn.provider_request_finished_at is None
    )


def _durable_provider_request_acknowledged(
    store: "RuntimeStore | None",
    *,
    lease: _PlainHostedRequestLease | None,
) -> bool:
    turn = _turn_for_exact_lease(store, lease=lease)
    if turn is None:
        return False
    requested_at = turn.cancellation_requested_at
    acknowledged_at = turn.provider_request_cancellation_acknowledged_at
    return bool(requested_at is not None and acknowledged_at is not None and acknowledged_at >= requested_at)


def _turn_for_exact_lease(store: "RuntimeStore | None", *, lease: _PlainHostedRequestLease | None):
    if store is None or lease is None:
        return None
    try:
        turn = store.get_turn(lease.turn_id)
    except RuntimeTurnNotFoundError:
        return None
    if (
        turn.provider_request_generation != lease.generation
        or turn.provider_request_started_at != lease.started_at
    ):
        return None
    return turn


def _current_process_owner() -> _PlainHostedProcessOwner:
    pid = os.getpid()
    host_id = socket.gethostname()
    process_start = _process_start_token(pid) or f"unverified:{_PROCESS_GENERATION}"
    return _PlainHostedProcessOwner(
        owner_id=f"process:{host_id}:{pid}:{process_start}:{_PROCESS_GENERATION}",
        owner_kind="process",
        host_id=host_id,
        pid=pid,
        process_start=process_start,
    )


def _provider_request_owner_is_alive(turn) -> bool:
    owner_kind = turn.provider_request_owner_kind
    owner_host_id = turn.provider_request_owner_host_id
    owner_pid = turn.provider_request_owner_pid
    owner_process_start = turn.provider_request_owner_process_start
    if owner_kind not in {None, "process"}:
        return True
    if owner_host_id not in {None, socket.gethostname()}:
        return True
    if owner_pid is None:
        owner_pid = _legacy_owner_pid(turn.provider_request_owner_id)
    if owner_pid is None:
        return True
    return _process_is_alive(owner_pid, expected_start=owner_process_start)


def _process_is_alive(pid: int, *, expected_start: str | None) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    current_start = _process_start_token(pid)
    if expected_start and current_start is not None:
        return current_start == expected_start
    return True


def _process_start_token(pid: int) -> str | None:
    try:
        raw_stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None
    command_end = raw_stat.rfind(")")
    if command_end < 0:
        return None
    fields_after_command = raw_stat[command_end + 2 :].split()
    return fields_after_command[19] if len(fields_after_command) > 19 else None


def _legacy_owner_pid(owner_id: str | None) -> int | None:
    parts = (owner_id or "").split(":")
    if len(parts) != 3 or parts[0] != "backend":
        return None
    try:
        pid = int(parts[1])
    except ValueError:
        return None
    return pid if pid > 0 else None
