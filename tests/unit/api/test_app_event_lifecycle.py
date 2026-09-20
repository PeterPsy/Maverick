"""Bounded app fanout and notification-driven WebSocket shutdown."""

import asyncio
from threading import Thread
import unittest

from core.api.app_events import APP_EVENTS_WS_PATH, AppEventBus, stream_app_events
from core.shared.entrypoints import EntrypointShutdownController


class AppEventLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_overflow_closes_then_new_subscription_converges(self):
        bus = AppEventBus()
        messages = []
        connected = asyncio.Event()

        async def send(message):
            messages.append(message)
            if message['type'] == 'websocket.accept':
                connected.set()

        task = asyncio.create_task(stream_app_events(
            bus=bus, scope={'path': APP_EVENTS_WS_PATH},
            receive=asyncio.Queue().get, send=send, workspace_id='a',
        ))
        await connected.wait()
        for revision in range(101):
            bus.publish({'workspace_id': 'a', 'revision': revision})
        await asyncio.wait_for(task, 1)
        self.assertEqual(messages[-1]['code'], 1013)
        self.assertEqual(messages[-1]['reason'], 'resync_required')
        self.assertEqual(len(bus._subscribers), 0)
        queue = bus.subscribe()
        bus.publish({'workspace_id': 'a', 'revision': 102})
        self.assertEqual((await queue.get())['revision'], 102)
        bus.unsubscribe(queue)

    async def test_parent_shutdown_from_thread_wakes_all_and_cleans_waiters(self):
        parent = EntrypointShutdownController()
        child = EntrypointShutdownController(parent=parent)
        tasks = [asyncio.create_task(child.wait_shutdown()) for _ in range(6)]
        await asyncio.sleep(0)
        self.assertEqual(len(parent._shutdown_waiters), 6)
        thread = Thread(target=parent.begin_shutdown)
        thread.start()
        await asyncio.wait_for(asyncio.gather(*tasks), 1)
        thread.join()
        self.assertFalse(parent._shutdown_waiters)
        self.assertFalse(child._shutdown_waiters)
        await asyncio.wait_for(child.wait_shutdown(), 1)

    async def test_cancelled_waiter_unregisters_from_parent_and_child(self):
        parent = EntrypointShutdownController()
        child = EntrypointShutdownController(parent=parent)
        task = asyncio.create_task(child.wait_shutdown())
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(parent._shutdown_waiters)
        self.assertFalse(child._shutdown_waiters)

    async def test_cancelling_stream_drains_its_children(self):
        bus = AppEventBus()
        controller = EntrypointShutdownController()
        connected = asyncio.Event()

        async def send(message):
            connected.set()

        task = asyncio.create_task(stream_app_events(
            bus=bus, scope={'path': APP_EVENTS_WS_PATH},
            receive=asyncio.Queue().get, send=send, shutdown_controller=controller,
        ))
        await connected.wait()
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(bus._subscribers)
        self.assertFalse(controller._shutdown_waiters)
