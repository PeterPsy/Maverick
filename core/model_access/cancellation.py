"""Atomic submission and cleanup fencing for revocable model requests."""

from __future__ import annotations

from contextlib import contextmanager
import logging
from threading import Event, RLock
from typing import Callable, Iterator, Protocol


logger = logging.getLogger(__name__)


class CancellationSignal(Protocol):
    """Event-compatible cancellation surface used by model transports."""

    def is_set(self) -> bool: ...

    def set(self) -> None: ...

    def wait(self, timeout: float | None = None) -> bool: ...


class ModelAccessRequestCancelled(RuntimeError):
    """Raised before a revoked request can cross an upstream submission boundary."""


class CancellationRegistration:
    """Idempotent handle for one live-resource cleanup callback."""

    def __init__(self, owner: ModelAccessCancellation | None, token: int | None) -> None:
        self._owner = owner
        self._token = token
        self._lock = RLock()

    def close(self) -> None:
        with self._lock:
            owner = self._owner
            token = self._token
            self._owner = None
            self._token = None
        if owner is not None and token is not None:
            owner._unregister(token)


class ModelAccessCancellation:
    """Linearize submission with revocation and synchronously close live resources."""

    def __init__(self) -> None:
        self._event = Event()
        self._lock = RLock()
        self._callbacks: dict[int, Callable[[], None]] = {}
        self._next_token = 1

    def is_set(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        return self._event.wait(timeout)

    def set(self) -> None:
        with self._lock:
            if self._event.is_set():
                return
            self._event.set()
            callbacks = tuple(self._callbacks.values())
            self._callbacks.clear()
        for callback in callbacks:
            try:
                callback()
            except Exception:
                logger.exception("Revoked model resource cleanup failed.")

    def raise_if_cancelled(self) -> None:
        with self._lock:
            if self._event.is_set():
                raise ModelAccessRequestCancelled("model request was revoked")

    @contextmanager
    def submission_fence(self) -> Iterator[None]:
        """Let either revocation or one external submission win atomically."""
        with self._lock:
            if self._event.is_set():
                raise ModelAccessRequestCancelled("model request was revoked")
            yield

    def register_cleanup(self, callback: Callable[[], None]) -> CancellationRegistration:
        """Register cleanup, or clean immediately if revocation already won."""
        with self._lock:
            if self._event.is_set():
                cancelled = True
                token = None
            else:
                cancelled = False
                token = self._next_token
                self._next_token += 1
                self._callbacks[token] = callback
        if cancelled:
            try:
                callback()
            finally:
                raise ModelAccessRequestCancelled("model request was revoked") from None
        return CancellationRegistration(self, token)

    def _unregister(self, token: int) -> None:
        with self._lock:
            self._callbacks.pop(token, None)


def raise_if_cancelled(cancellation: CancellationSignal) -> None:
    """Fail before submission for both broker signals and simple test events."""
    if isinstance(cancellation, ModelAccessCancellation):
        cancellation.raise_if_cancelled()
    elif cancellation.is_set():
        raise ModelAccessRequestCancelled("model request was revoked")


@contextmanager
def submission_fence(cancellation: CancellationSignal) -> Iterator[None]:
    """Use the atomic broker fence, with a conservative Event fallback."""
    if isinstance(cancellation, ModelAccessCancellation):
        with cancellation.submission_fence():
            yield
        return
    raise_if_cancelled(cancellation)
    yield


def register_cleanup(
    cancellation: CancellationSignal,
    callback: Callable[[], None],
) -> CancellationRegistration:
    """Bind a live resource to cancellation before it becomes externally active."""
    if isinstance(cancellation, ModelAccessCancellation):
        return cancellation.register_cleanup(callback)
    if cancellation.is_set():
        try:
            callback()
        finally:
            raise ModelAccessRequestCancelled("model request was revoked") from None
    return CancellationRegistration(None, None)


__all__ = [
    "CancellationRegistration",
    "CancellationSignal",
    "ModelAccessCancellation",
    "ModelAccessRequestCancelled",
    "raise_if_cancelled",
    "register_cleanup",
    "submission_fence",
]
