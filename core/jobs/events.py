"""Live fanout for already-persisted durable job events."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from threading import RLock

from core.jobs.records import JobEventRecord


@dataclass(frozen=True)
class JobEventSubscription:
    workspace_id: str
    queue: asyncio.Queue[JobEventRecord]

    async def get(self) -> JobEventRecord:
        return await self.queue.get()


@dataclass(frozen=True)
class _Subscriber:
    workspace_id: str
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[JobEventRecord]


class JobEventBus:
    """Fan out persisted job events to workspace-scoped subscribers."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._subscribers: dict[int, _Subscriber] = {}
        self._next_id = 0

    def subscribe(self, workspace_id: str) -> JobEventSubscription:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[JobEventRecord] = asyncio.Queue(maxsize=200)
        with self._lock:
            subscription_id = self._next_id
            self._next_id += 1
            self._subscribers[subscription_id] = _Subscriber(workspace_id, loop, queue)
        return JobEventSubscription(workspace_id, queue)

    def unsubscribe(self, subscription: JobEventSubscription) -> None:
        with self._lock:
            for subscription_id, subscriber in list(self._subscribers.items()):
                if subscriber.queue is subscription.queue:
                    self._subscribers.pop(subscription_id, None)
                    return

    def publish(self, event: JobEventRecord) -> None:
        with self._lock:
            subscribers = [
                subscriber
                for subscriber in self._subscribers.values()
                if subscriber.workspace_id == event.workspace_id
            ]
        for subscriber in subscribers:
            subscriber.loop.call_soon_threadsafe(_put_bounded, subscriber.queue, event)


def _put_bounded(queue: asyncio.Queue[JobEventRecord], event: JobEventRecord) -> None:
    try:
        queue.put_nowait(event)
    except asyncio.QueueFull:
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
        queue.put_nowait(event)
