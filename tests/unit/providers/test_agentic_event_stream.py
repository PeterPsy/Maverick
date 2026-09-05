"""Consumers close owned generators without narrowing the iterator contract."""

import unittest

from core.providers.agentic_event_stream import closing_runtime_events


class AgenticEventStreamTest(unittest.IsolatedAsyncioTestCase):
    async def test_consumer_failure_closes_the_generator_once_before_returning(self):
        closed = []

        async def events():
            try:
                yield "event"
            finally:
                closed.append(True)

        with self.assertRaisesRegex(ValueError, "consumer failed"):
            async with closing_runtime_events(events()) as stream:
                async for _event in stream:
                    raise ValueError("consumer failed")
        self.assertEqual(closed, [True])

    async def test_non_closeable_async_iterators_remain_valid(self):
        class Events:
            def __aiter__(self):
                return self

            async def __anext__(self):
                raise StopAsyncIteration

        async with closing_runtime_events(Events()) as stream:
            self.assertEqual([event async for event in stream], [])
