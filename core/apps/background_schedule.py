"""Backend-owned due times; app code is never spawned merely to check a deadline."""

from math import isfinite
import time


class BackgroundHookSchedule:
    def __init__(self, default_interval: float = 15.0, *, clock=time.monotonic):
        self.default_interval = default_interval
        self.clock = clock
        self.entries: dict[tuple[str, str, str], tuple[float, str]] = {}

    def due(self, key: tuple[str, str, str], revision: str) -> bool:
        deadline, previous = self.entries.get(key, (0.0, revision))
        return previous != revision or self.clock() >= deadline

    def complete(self, key: tuple[str, str, str], revision: str, result: dict | None) -> None:
        delay = (result or {}).get('next_due_in_seconds', self.default_interval)
        if not isinstance(delay, (float, int)) or isinstance(delay, bool) or not isfinite(delay):
            delay = self.default_interval
        self.entries[key] = (self.clock() + min(3600.0, max(1.0, delay)), revision)

    def prune_apps(self, workspace: str, enabled: set[str]) -> None:
        for key in list(self.entries):
            if key[0] == workspace and key[1] not in enabled:
                del self.entries[key]

    def prune_workspaces(self, active: set[str]) -> None:
        for key in list(self.entries):
            if key[0] not in active:
                del self.entries[key]

    def next_delay(self) -> float:
        now = self.clock()
        return max(1.0, min([self.default_interval, *(deadline - now for deadline, _ in self.entries.values())]))
