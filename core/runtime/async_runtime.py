"""Safe synchronous entrypoint for async runtime adapter operations."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from threading import Thread
from typing import Any, TypeVar


T = TypeVar("T")


def run_runtime_coroutine(coroutine: Coroutine[Any, Any, T]) -> T:
    """Run one adapter coroutine even when the caller already owns an event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    result: list[T] = []
    failures: list[BaseException] = []

    def worker() -> None:
        try:
            result.append(asyncio.run(coroutine))
        except BaseException as error:
            failures.append(error)

    thread = Thread(target=worker, name="maverick-agentic-async-bridge")
    thread.start()
    thread.join()
    if failures:
        raise failures[0]
    return result[0]
