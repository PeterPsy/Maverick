"""OpenRouter live-probe matrix regressions without network access."""

from __future__ import annotations

import asyncio
from unittest import mock
import unittest

from core.providers.agentic_protocol import (
    AgenticModelEvent,
    AgenticProviderPrivateState,
    AgenticToolCall,
    AgenticUsage,
)
from scripts import run_openrouter_agentic_probe as probe


class _ProbeClient:
    def __init__(self) -> None:
        self.requests = []

    async def create_response(self, request, *, credential):
        self.requests.append(request)
        if request.tool_results:
            yield AgenticModelEvent(
                "text_final",
                request.request_id,
                1,
                text="OK",
            )
        else:
            yield AgenticModelEvent(
                "tool_call",
                request.request_id,
                1,
                tool_call=AgenticToolCall(
                    "probe-call",
                    "maverick_probe_echo",
                    {"ok": True},
                ),
            )
        yield AgenticModelEvent(
            "provider_state",
            request.request_id,
            2,
            provider_private_state=AgenticProviderPrivateState(
                "probe-codec",
                "1",
                "1",
                "application/json",
                b"{}",
            ),
        )
        yield AgenticModelEvent(
            "usage",
            request.request_id,
            3,
            usage=AgenticUsage(10, 2, 1),
        )
        yield AgenticModelEvent("completed", request.request_id, 4)


class OpenRouterAgenticProbeTest(unittest.TestCase):
    def test_probe_covers_every_certified_reasoning_effort(self) -> None:
        client = _ProbeClient()
        with mock.patch.dict(
            "os.environ",
            {"MAVERICK_OPENROUTER_CERTIFICATION_API_KEY": "synthetic-key"},
        ), mock.patch.object(
            probe,
            "OpenRouterAgenticClient",
            return_value=client,
        ):
            exit_code = asyncio.run(probe._main())

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(client.requests), 8)
        self.assertEqual(
            [request.reasoning_effort for request in client.requests],
            [
                effort
                for effort in probe.CERTIFIED_REASONING_EFFORTS
                for _ in range(2)
            ],
        )
        self.assertTrue(
            all(
                request.request_id.endswith((":1", ":2"))
                for request in client.requests
            )
        )


if __name__ == "__main__":
    unittest.main()
