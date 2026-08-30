"""Thread-safe cancellation with an explicit effect linearization gate."""

from __future__ import annotations

from collections.abc import Callable
from threading import Event, RLock
from typing import TypeVar


_T = TypeVar("_T")


class RuntimeCancellationSignal:
    """One-shot signal that serializes cancellation against effect commits.

    Callers that cross an irreversible boundary must use ``run_if_active``.
    ``set`` and that boundary then share the same lock: either the action has
    linearized first, or cancellation has and the action is not invoked.
    """

    def __init__(self) -> None:
        self._event = Event()
        self._lock = RLock()
        self._callbacks: dict[int, Callable[[], None]] = {}
        self._next_callback_id = 0

    def is_set(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        return self._event.wait(timeout)

    def set(self) -> bool:
        """Signal once and synchronously run registered cancellation cleanup."""
        with self._lock:
            if self._event.is_set():
                return False
            self._event.set()
            callbacks = tuple(self._callbacks.values())
            self._callbacks.clear()
        for callback in callbacks:
            try:
                callback()
            except Exception:
                pass
        return True

    def add_callback(self, callback: Callable[[], None]) -> int | None:
        """Register cleanup without losing cancellation concurrent with setup."""
        call_now = False
        callback_id: int | None = None
        with self._lock:
            if self._event.is_set():
                call_now = True
            else:
                callback_id = self._next_callback_id
                self._next_callback_id += 1
                self._callbacks[callback_id] = callback
        if call_now:
            callback()
        return callback_id

    def remove_callback(self, callback_id: int | None) -> None:
        if callback_id is None:
            return
        with self._lock:
            self._callbacks.pop(callback_id, None)

    def run_if_active(
        self,
        action: Callable[[], _T],
        *,
        cancelled: Callable[[], _T],
    ) -> _T:
        """Run one action atomically before cancellation or reject it."""
        with self._lock:
            if self._event.is_set():
                return cancelled()
            return action()


__all__ = ["RuntimeCancellationSignal"]
