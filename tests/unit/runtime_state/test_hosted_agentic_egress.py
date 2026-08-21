from __future__ import annotations

import json
import unittest

from core.runtime.execution import execute_runtime_turn
from tests.support.fake_agentic_provider import DeterministicFakeAgenticClient
from tests.support.hosted_agentic_harness import HostedAgenticHarness


class HostedAgenticEgressTest(unittest.TestCase):
    def test_tool_result_host_paths_are_redacted_before_the_next_request(self) -> None:
        harness = HostedAgenticHarness(self)
        harness.read_result = {
            "workspace_file": f"{harness.session.workspace_root}/AGENTS.md",
            "host_reference": (
                "The installation root is `/home/ubuntu/projects/maverick-v3`."
            ),
        }
        client = DeterministicFakeAgenticClient(tool_name=harness.read_tool_name)

        result = execute_runtime_turn(
            session=harness.session,
            provider=harness.provider,
            input_text="Use only synthetic fixture data.",
            agentic_adapter=harness.adapter(client),
            provider_state=harness.store.get_provider_state("session-hosted"),
            correlation_id="turn-hosted",
            effective_authority=harness.authority,
        )

        self.assertEqual(result.exit_code, 0)
        exported = json.loads(client.requests[1].tool_results[0].content)
        self.assertEqual(exported["workspace_file"], "workspace://default/AGENTS.md")
        self.assertEqual(
            exported["host_reference"],
            "The installation root is `<redacted-host-path>`.",
        )
        decisions = harness.store.list_egress_decisions(session_id="session-hosted")
        tool_result = next(
            decision for decision in decisions if decision.provenance == "tool_result"
        )
        self.assertEqual(
            tool_result.transformation,
            "workspace_path_reference+host_path_redaction",
        )


if __name__ == "__main__":
    unittest.main()
