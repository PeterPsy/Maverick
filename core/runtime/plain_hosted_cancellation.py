"""Local handles backed by durable cancellation fences for hosted requests."""

from __future__ import annotations

from contextlib import contextmanager, suppress
import os
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


def plain_hosted_request_owner_id() -> str:
    """Return the stable identity for this backend process incarnation."""
    return f"backend:{os.getpid()}:{_PROCESS_GENERATION}"


def reconcile_stale_plain_hosted_request_owners(store: "RuntimeStore") -> int:
    """Close unfinished request leases owned by a previous backend process."""
    return store.reconcile_stale_turn_provider_requests(
        active_owner_id=plain_hosted_request_owner_id(),
    )


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
            owner_id = plain_hosted_request_owner_id()
            request_generation = uuid4().hex
            tracked = store.mark_turn_provider_request_started(
                turn_id=turn_id,
                owner_id=owner_id,
                generation=request_generation,
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
                )


def interrupt_plain_hosted_requests(
    session_id: str,
    *,
    store: "RuntimeStore | None" = None,
    wait_for_termination: bool = False,
) -> bool:
    """Cancel local handles and optionally await a remote owner's durable ack."""
    with _ACTIVE_REQUESTS_LOCK:
        cancellations = [
            cancellation
            for (active_session_id, _turn_id), cancellation in _ACTIVE_REQUESTS.items()
            if active_session_id == session_id
        ]
    for cancellation in cancellations:
        cancellation.cancel()
    remote_active = _durable_provider_requests_inflight(store, session_id=session_id)
    remote_request_observed = bool(remote_active)
    if wait_for_termination:
        deadline = time.monotonic() + _TERMINATION_WAIT_SECONDS
        unfinished_local = False
        for cancellation in cancellations:
            if not cancellation.wait_finished(timeout=max(0.0, deadline - time.monotonic())):
                unfinished_local = True
        while remote_active and time.monotonic() < deadline:
            time.sleep(_CANCELLATION_POLL_SECONDS)
            remote_active = _durable_provider_requests_inflight(store, session_id=session_id)
        if unfinished_local or remote_active:
            raise TimeoutError(
                f"Plain-hosted provider request for runtime session `{session_id}` did not stop after cancellation."
            )
    return bool(cancellations or remote_request_observed)


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


def _durable_provider_requests_inflight(
    store: "RuntimeStore | None",
    *,
    session_id: str,
) -> list[str]:
    if store is None:
        return []
    turns = store.list_turns(session_id)
    return [
        turn.turn_id
        for turn in turns
        if turn.cancellation_requested_at is not None
        and turn.provider_request_started_at is not None
        and turn.provider_request_finished_at is None
    ]
