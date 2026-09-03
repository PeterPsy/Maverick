from __future__ import annotations

from dataclasses import replace
import unittest

from core.runtime.execution import execute_runtime_turn
from tests.support.fake_agentic_provider import DeterministicFakeAgenticClient
from tests.support.hosted_agentic_harness import HostedAgenticHarness


class HostedAgenticLastMileBudgetTest(unittest.TestCase):
    def test_last_mile_tool_ceiling_tightening_rebuilds_toolless_request(self) -> None:
        harness = HostedAgenticHarness(self, max_tool_calls=2)
        live_policy = harness.policy
        refresh_calls = 0

        def refresh(_context):
            nonlocal live_policy, refresh_calls
            refresh_calls += 1
            if refresh_calls == 6:
                live_policy = replace(
                    live_policy,
                    max_tool_calls_per_turn=1,
                )
            return harness.authority

        client = DeterministicFakeAgenticClient(
            tool_name=harness.read_tool_name,
        )
        result = execute_runtime_turn(
            session=harness.session,
            provider=harness.provider,
            input_text="Use only synthetic fixture data.",
            agentic_adapter=harness.adapter(
                client,
                policy_resolver=lambda _context: live_policy,
                authority_refresher=refresh,
                authority_revalidator=lambda _context, current: current,
            ),
            provider_state=harness.store.get_provider_state("session-hosted"),
            correlation_id="turn-hosted",
            effective_authority=harness.authority,
        )

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(harness.cli_calls, 1)
        self.assertEqual(
            [request.request_phase for request in client.requests],
            ["exploration", "finalization"],
        )
        self.assertTrue(client.requests[0].tool_definitions)
        self.assertEqual(client.requests[1].tool_definitions, ())
        journals = harness.store.list_provider_step_journals(
            session_id="session-hosted"
        )
        self.assertEqual(
            [(record.step_index, record.request_phase) for record in journals],
            [(0, "exploration"), (1, "finalization")],
        )

    def test_lazy_open_tool_ceiling_tightening_blocks_stale_catalog(self) -> None:
        harness = HostedAgenticHarness(self, max_tool_calls=2)
        live_policy = harness.policy
        refresh_calls = 0

        def refresh(_context):
            nonlocal live_policy, refresh_calls
            refresh_calls += 1
            if refresh_calls == 8:
                live_policy = replace(
                    live_policy,
                    max_tool_calls_per_turn=1,
                )
            return harness.authority

        client = DeterministicFakeAgenticClient(
            tool_name=harness.read_tool_name,
        )
        result = execute_runtime_turn(
            session=harness.session,
            provider=harness.provider,
            input_text="Use only synthetic fixture data.",
            agentic_adapter=harness.adapter(
                client,
                policy_resolver=lambda _context: live_policy,
                authority_refresher=refresh,
                authority_revalidator=lambda _context, current: current,
            ),
            provider_state=harness.store.get_provider_state("session-hosted"),
            correlation_id="turn-hosted",
            effective_authority=harness.authority,
        )

        self.assertEqual(refresh_calls, 8)
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(
            result.failure_reason_code,
            "agent_tool_call_limit_reached",
        )
        self.assertEqual(len(client.requests), 1)
        self.assertTrue(client.requests[0].tool_definitions)

    def test_exhausted_total_tool_result_budget_forces_toolless_request(self) -> None:
        harness = HostedAgenticHarness(self, max_tool_calls=2)
        harness.policy = replace(
            harness.policy,
            max_total_tool_result_bytes=len(b'{"value":4}'),
        )
        client = DeterministicFakeAgenticClient(
            tool_name=harness.read_tool_name,
        )
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
        self.assertEqual(harness.cli_calls, 1)
        self.assertEqual(
            [request.request_phase for request in client.requests],
            ["exploration", "finalization"],
        )
        self.assertTrue(client.requests[0].tool_definitions)
        self.assertEqual(client.requests[1].tool_definitions, ())


if __name__ == "__main__":
    unittest.main()
