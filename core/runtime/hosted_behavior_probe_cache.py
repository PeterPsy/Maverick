"""Success-only cache for executable hosted behavior evidence."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from threading import RLock


BehaviorProbe = Callable[[], tuple[str, ...]]


def cache_complete_behavior_probe(
    expected: tuple[str, ...],
) -> Callable[[BehaviorProbe], BehaviorProbe]:
    """Cache a probe only after it returns its complete expected evidence."""

    def decorate(probe: BehaviorProbe) -> BehaviorProbe:
        lock = RLock()
        cached: tuple[str, ...] | None = None

        @wraps(probe)
        def inspect() -> tuple[str, ...]:
            nonlocal cached
            with lock:
                if cached is not None:
                    return cached
            result = probe()
            if result != expected:
                return result
            with lock:
                if cached is None:
                    cached = result
                return cached

        def cache_clear() -> None:
            nonlocal cached
            with lock:
                cached = None

        inspect.cache_clear = cache_clear  # type: ignore[attr-defined]
        return inspect

    return decorate


__all__ = ["cache_complete_behavior_probe"]
