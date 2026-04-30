"""In-memory runtime event fanout for live transports."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from threading import RLock

from core.runtime.runtime_events import RuntimeEventRecord


@dataclass(frozen=True)
class RuntimeEventSubscription:
    """One live runtime event subscription bound to an asyncio loop."""

    session_id: str
    queue: asyncio.Queue[RuntimeEventRecord]

    async def get(self) -> RuntimeEventRecord:
        """Wait for the next event published for this subscription."""
        return await self.queue.get()


@dataclass(frozen=True)
class _Subscriber:
    session_id: str
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[RuntimeEventRecord]


class RuntimeEventBus:
    """Fan out persisted runtime events to live session subscribers."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._subscribers: dict[int, _Subscriber] = {}
        self._next_subscription_id = 0

    def subscribe(self, session_id: str) -> RuntimeEventSubscription:
        """Subscribe the current asyncio loop to live events for one session."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[RuntimeEventRecord] = asyncio.Queue()
        with self._lock:
            subscription_id = self._next_subscription_id
            self._next_subscription_id += 1
            self._subscribers[subscription_id] = _Subscriber(session_id=session_id, loop=loop, queue=queue)
        return RuntimeEventSubscription(session_id=session_id, queue=queue)

    def unsubscribe(self, subscription: RuntimeEventSubscription) -> None:
        """Remove one subscription from the fanout table."""
        with self._lock:
            for subscription_id, subscriber in list(self._subscribers.items()):
                if subscriber.queue is subscription.queue:
                    self._subscribers.pop(subscription_id, None)
                    return

    def publish(self, event: RuntimeEventRecord) -> None:
        """Publish one already-persisted runtime event to current subscribers."""
        with self._lock:
            subscribers = [subscriber for subscriber in self._subscribers.values() if subscriber.session_id == event.session_id]
        for subscriber in subscribers:
            subscriber.loop.call_soon_threadsafe(subscriber.queue.put_nowait, event)
