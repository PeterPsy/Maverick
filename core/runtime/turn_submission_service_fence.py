"""Caller-provided atomic fence for runtime turn queue creation."""

from __future__ import annotations

from contextlib import nullcontext
from typing import Callable, ContextManager


RuntimeTurnQueueFence = Callable[[], ContextManager[None]]


def runtime_turn_queue_fence(queue_fence: RuntimeTurnQueueFence | None) -> ContextManager[None]:
    """Return the caller fence or a no-op context for ordinary submissions."""
    return nullcontext() if queue_fence is None else queue_fence()
