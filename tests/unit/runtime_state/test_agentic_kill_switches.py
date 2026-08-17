"""Live narrowing tests for operational agentic kill switches."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from core.runtime.agentic_feature_flags import MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME
from core.runtime.execution import execute_runtime_turn
from core.runtime.execution_events import RuntimeExecutionEvent
from tests.support.fake_agentic_provider import DeterministicFakeAgenticClient
from tests.support.hosted_agentic_harness import HostedAgenticHarness


class AgenticKillSwitchTest(unittest.TestCase):
    def test_hosted_runtime_blocks_before_provider_dispatch(self) -> None:
        harness = HostedAgenticHarness(self)
        client = DeterministicFakeAgenticClient(tool_name=harness.read_tool_name)
        events: list[RuntimeExecutionEvent] = []

        with patch.dict(
            "os.environ",
            {MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME: "0"},
            clear=False,
        ):
            result = execute_runtime_turn(
                session=harness.session,
                provider=harness.provider,
                input_text="Use only synthetic fixture data.",
                agentic_adapter=harness.adapter(client),
                provider_state=harness.store.get_provider_state("session-hosted"),
                correlation_id="turn-hosted",
                effective_authority=harness.authority,
                event_sink=events.append,
            )

        self.assertEqual(result.exit_code, 1)
        self.assertEqual(client.requests, [])
        self.assertEqual(events[-1].payload["reason_code"], "hosted_agent_runtime_disabled")


if __name__ == "__main__":
    unittest.main()
