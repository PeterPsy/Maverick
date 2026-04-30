"""In-memory runtime thread event fanout for live transports."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from threading import RLock
from typing import Any


@dataclass(frozen=True)
class RuntimeThreadEventSubscription:
    """One live runtime thread event subscription bound to an asyncio loop."""

    workspace_id: str
    queue: asyncio.Queue[dict[str, Any]]

    async def get(self) -> dict[str, Any]:
        """Wait for the next event published for this subscription."""
        return await self.queue.get()


@dataclass(frozen=True)
class _Subscriber:
    workspace_id: str
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[dict[str, Any]]


class RuntimeThreadEventBus:
    """Fan out runtime thread events to live thread subscribers."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._subscribers: dict[int, _Subscriber] = {}
        self._next_subscription_id = 0

    def subscribe(self, workspace_id: str) -> RuntimeThreadEventSubscription:
        """Subscribe the current asyncio loop to live thread events for one workspace."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        with self._lock:
            subscription_id = self._next_subscription_id
            self._next_subscription_id += 1
            self._subscribers[subscription_id] = _Subscriber(workspace_id=workspace_id, loop=loop, queue=queue)
        return RuntimeThreadEventSubscription(workspace_id=workspace_id, queue=queue)

    def unsubscribe(self, subscription: RuntimeThreadEventSubscription) -> None:
        """Remove one subscription from the fanout table."""
        with self._lock:
            for subscription_id, subscriber in list(self._subscribers.items()):
                if subscriber.queue is subscription.queue:
                    self._subscribers.pop(subscription_id, None)
                    return

    def publish(self, *, workspace_id: str, event: dict[str, Any]) -> None:
        """Publish one runtime thread event to current subscribers."""
        with self._lock:
            subscribers = [subscriber for subscriber in self._subscribers.values() if subscriber.workspace_id == workspace_id]
        for subscriber in subscribers:
            subscriber.loop.call_soon_threadsafe(subscriber.queue.put_nowait, event)
