from __future__ import annotations

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.runtime.hosted_agentic_models import HostedAgenticLoopError
from core.runtime.hosted_agentic_tool_batch import execute_hosted_tool_batch
from core.runtime.runtime_cancellation import RuntimeCancellationSignal


class HostedAgenticToolBatchTest(unittest.IsolatedAsyncioTestCase):
    async def test_cancellation_reaches_every_started_batch_worker(self) -> None:
        both_started = asyncio.Event()
        started: list[object] = []

        async def execute(**arguments):
            started.append(arguments["outcome"])
            if len(started) == 2:
                both_started.set()
            await both_started.wait()
            raise HostedAgenticLoopError("runtime_cancelled")

        prepared = [
            SimpleNamespace(
                orchestrator=object(),
                outcome=object(),
                authority=object(),
                actor_context=object(),
                tool_policy=object(),
            )
            for _index in range(2)
        ]
        with patch(
            "core.runtime.hosted_agentic_tool_batch.execute_hosted_authorized_tool",
            side_effect=execute,
        ):
            with self.assertRaisesRegex(HostedAgenticLoopError, "runtime_cancelled"):
                await execute_hosted_tool_batch(
                    prepared,
                    (0, 1),
                    budget=object(),
                    cancellation=RuntimeCancellationSignal(),
                    poll_seconds=0.01,
                    terminalize=lambda _orchestrator, outcome: outcome,
                )

        self.assertEqual(len(started), 2)

    async def test_worker_error_is_terminalized_without_cancelling_sibling(self) -> None:
        completed = object()
        terminalized = object()
        calls = 0

        async def execute(**_arguments):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("private worker failure")
            return completed

        prepared = [
            SimpleNamespace(
                orchestrator=object(),
                outcome=object(),
                authority=object(),
                actor_context=object(),
                tool_policy=object(),
            )
            for _index in range(2)
        ]
        with patch(
            "core.runtime.hosted_agentic_tool_batch.execute_hosted_authorized_tool",
            side_effect=execute,
        ):
            await execute_hosted_tool_batch(
                prepared,
                (0, 1),
                budget=object(),
                cancellation=RuntimeCancellationSignal(),
                poll_seconds=0.01,
                terminalize=lambda _orchestrator, _outcome: terminalized,
            )

        self.assertEqual(calls, 2)
        self.assertIs(prepared[0].outcome, terminalized)
        self.assertIs(prepared[1].outcome, completed)


if __name__ == "__main__":
    unittest.main()
