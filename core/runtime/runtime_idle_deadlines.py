"""One idle-resource owner for delayed prewarm and process retirement."""

from collections.abc import Callable
from dataclasses import dataclass
import logging
from threading import Condition, Thread
import time

logger = logging.getLogger(__name__)


@dataclass
class _IdleDeadline:
    at: float
    callback: Callable[[], None]
    retention_group: tuple[str, str] | None


class RuntimeIdleDeadlines:
    def __init__(self):
        self._condition = Condition()
        self._pending: dict[tuple[int, str, str], _IdleDeadline] = {}
        self._thread: Thread | None = None

    def schedule(
        self, owner: object, session: str, action: str, delay: float, callback: Callable[[], None],
        *, retention_group: tuple[str, str] | None = None,
    ) -> None:
        with self._condition:
            now = time.monotonic()
            key = (id(owner), session, action)
            if retention_group is not None:
                for previous_key, previous in self._pending.items():
                    if (previous_key != key and previous_key[0] == id(owner)
                            and previous_key[2] == action and previous.retention_group == retention_group):
                        # Dispatch the old retirement outside the condition and the
                        # caller's session fence. Its active-turn guard still applies.
                        previous.at = min(previous.at, now)
            self._pending[key] = _IdleDeadline(now + max(0, delay), callback, retention_group)
            if self._thread is None:
                self._thread = Thread(target=self._run, name='maverick-runtime-idle-resources', daemon=True)
                self._thread.start()
            self._condition.notify()

    def cancel(self, owner: object, session: str, action: str) -> None:
        with self._condition:
            self._pending.pop((id(owner), session, action), None)
            self._condition.notify()

    def pending(self, owner: object, session: str, action: str) -> bool:
        with self._condition:
            return (id(owner), session, action) in self._pending

    def cancel_owner(self, owner: object) -> None:
        with self._condition:
            for key in list(self._pending):
                if key[0] == id(owner):
                    del self._pending[key]
            self._condition.notify()

    def _run(self) -> None:
        while True:
            with self._condition:
                if not self._pending:
                    self._thread = None
                    return
                key, deadline = min(self._pending.items(), key=lambda item: item[1].at)
                remaining = deadline.at - time.monotonic()
                if remaining > 0:
                    self._condition.wait(remaining)
                    continue
                del self._pending[key]
            try:
                deadline.callback()
            except Exception:
                logger.exception('Runtime idle-resource task failed: session=%s action=%s', key[1], key[2])


runtime_idle_deadlines = RuntimeIdleDeadlines()
