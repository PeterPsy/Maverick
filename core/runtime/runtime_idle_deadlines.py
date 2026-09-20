"""One idle-resource owner for delayed prewarm and process retirement."""

from collections.abc import Callable
import logging
from threading import Condition, Thread
import time

logger = logging.getLogger(__name__)


class RuntimeIdleDeadlines:
    def __init__(self):
        self._condition = Condition()
        self._pending: dict[tuple[int, str, str], tuple[float, Callable[[], None]]] = {}
        self._thread: Thread | None = None

    def schedule(self, owner: object, session: str, action: str, delay: float, callback: Callable[[], None]) -> None:
        with self._condition:
            self._pending[(id(owner), session, action)] = (time.monotonic() + max(0, delay), callback)
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
                key, (deadline, callback) = min(self._pending.items(), key=lambda item: item[1][0])
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    self._condition.wait(remaining)
                    continue
                del self._pending[key]
            try:
                callback()
            except Exception:
                logger.exception('Runtime idle-resource task failed: session=%s action=%s', key[1], key[2])


runtime_idle_deadlines = RuntimeIdleDeadlines()
