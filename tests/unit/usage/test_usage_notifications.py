"""Live usage snapshots coalesce on the subscriber loop; observations remain durable."""

import asyncio
from datetime import UTC, datetime
import unittest
from unittest.mock import patch

from core.runtime.event_bus import RuntimeEventBus
from core.runtime.runtime_events import RuntimeEventRecord


def usage(identity):
    return RuntimeEventRecord(str(identity), 'workspace', 'root', 'runtime', 'runtime.usage.updated',
        None, None, {'sample_count': identity}, datetime.now(UTC))


class UsageNotificationsTests(unittest.IsolatedAsyncioTestCase):
    async def test_burst_has_leading_trailing_and_immediate_terminal_snapshot(self):
        bus = RuntimeEventBus()
        subscription = bus.subscribe('root')
        loop = asyncio.get_running_loop()
        loop.set_debug(False)
        with patch.object(loop, 'time', return_value=100.) as clock:
            for index in range(1, 101):
                bus.publish(usage(index))
            await asyncio.sleep(0)
            self.assertEqual(subscription.queue.qsize(), 1)
            self.assertEqual(subscription.queue.get_nowait().payload['sample_count'], 1)
            clock.return_value = 100.5
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            self.assertEqual(subscription.queue.get_nowait().payload['sample_count'], 100)
            bus.publish(usage(101))
            await asyncio.sleep(0)
            self.assertTrue(subscription.queue.empty())
            bus.flush_usage('root')
            await asyncio.sleep(0)
            self.assertEqual(subscription.queue.get_nowait().payload['sample_count'], 101)
        bus.unsubscribe(subscription)

    async def test_unsubscribe_cancels_pending_trailing_callback(self):
        bus = RuntimeEventBus()
        subscription = bus.subscribe('root')
        bus.publish(usage(1))
        bus.publish(usage(2))
        await asyncio.sleep(0)
        subscriber = next(iter(bus._subscribers.values()))
        timer = subscriber.usage_timer
        self.assertIsNotNone(timer)
        bus.unsubscribe(subscription)
        await asyncio.sleep(0)
        self.assertTrue(timer.cancelled())
        self.assertIsNone(subscriber.usage_pending)
        self.assertEqual(subscription.queue.qsize(), 1)
