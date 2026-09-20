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


@dataclass
class _Subscriber:
    session_id: str
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[RuntimeEventRecord]
    usage_pending: RuntimeEventRecord | None = None
    usage_timer: asyncio.TimerHandle | None = None
    usage_last_at: float = float("-inf")
    active: bool = True


class RuntimeEventBus:
    """Fan out durable events and coalesce disposable Usage snapshots per live transport."""

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
                    subscriber.active = False
                    if subscriber.usage_timer is not None:
                        subscriber.loop.call_soon_threadsafe(subscriber.usage_timer.cancel)
                    subscriber.usage_pending = None
                    return

    def publish(self, event: RuntimeEventRecord) -> None:
        """Publish an event; Usage observations are durable in their own store, not this log."""
        with self._lock:
            subscribers = [subscriber for subscriber in self._subscribers.values() if subscriber.session_id == event.session_id]
        for subscriber in subscribers:
            callback = self._offer_usage if event.event_type == 'runtime.usage.updated' else self._deliver
            if not subscriber.loop.is_closed():
                subscriber.loop.call_soon_threadsafe(callback, subscriber, event)

    @staticmethod
    def _deliver(subscriber: _Subscriber, event: RuntimeEventRecord) -> None:
        if subscriber.active:
            subscriber.queue.put_nowait(event)

    @classmethod
    def _offer_usage(cls, subscriber: _Subscriber, event: RuntimeEventRecord) -> None:
        if not subscriber.active:
            return
        subscriber.usage_pending = event
        delay = max(0., subscriber.usage_last_at + .5 - subscriber.loop.time())
        if delay == 0:
            cls._flush_usage(subscriber)
        elif subscriber.usage_timer is None:
            subscriber.usage_timer = subscriber.loop.call_later(delay, cls._flush_usage, subscriber)

    @staticmethod
    def _flush_usage(subscriber: _Subscriber) -> None:
        if subscriber.usage_timer is not None:
            subscriber.usage_timer.cancel()
            subscriber.usage_timer = None
        event, subscriber.usage_pending = subscriber.usage_pending, None
        if subscriber.active and event is not None:
            subscriber.usage_last_at = subscriber.loop.time()
            subscriber.queue.put_nowait(event)

    def flush_usage(self, session_id: str) -> None:
        """A terminal result bypasses throttling and flushes the latest committed snapshot."""
        with self._lock:
            subscribers = [item for item in self._subscribers.values() if item.session_id == session_id]
        for subscriber in subscribers:
            if not subscriber.loop.is_closed():
                subscriber.loop.call_soon_threadsafe(self._flush_usage, subscriber)
