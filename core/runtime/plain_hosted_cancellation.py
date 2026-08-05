"""Process-local cancellation registry for plain-hosted provider requests."""

from __future__ import annotations

from contextlib import contextmanager
from threading import Lock
from typing import Iterator

from core.providers.text_generation import HostedTextCancellation


_ACTIVE_REQUESTS: dict[tuple[str, str | None], HostedTextCancellation] = {}
_ACTIVE_REQUESTS_LOCK = Lock()


@contextmanager
def plain_hosted_request_cancellation(
    *,
    session_id: str,
    turn_id: str | None,
) -> Iterator[HostedTextCancellation]:
    """Register one cancellable request until its provider call has unwound."""
    key = (session_id, turn_id)
    cancellation = HostedTextCancellation()
    with _ACTIVE_REQUESTS_LOCK:
        if key in _ACTIVE_REQUESTS:
            raise RuntimeError(f"Plain-hosted provider request `{turn_id or session_id}` is already active.")
        _ACTIVE_REQUESTS[key] = cancellation
    try:
        yield cancellation
    finally:
        cancellation.mark_finished()
        with _ACTIVE_REQUESTS_LOCK:
            if _ACTIVE_REQUESTS.get(key) is cancellation:
                _ACTIVE_REQUESTS.pop(key, None)


def interrupt_plain_hosted_requests(
    session_id: str,
    *,
    wait_for_termination: bool = False,
) -> bool:
    """Cancel active requests and optionally wait until their calls unwind."""
    with _ACTIVE_REQUESTS_LOCK:
        cancellations = [
            cancellation
            for (active_session_id, _turn_id), cancellation in _ACTIVE_REQUESTS.items()
            if active_session_id == session_id
        ]
    for cancellation in cancellations:
        cancellation.cancel()
    if wait_for_termination:
        for cancellation in cancellations:
            cancellation.wait_finished()
    return bool(cancellations)
