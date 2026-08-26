from __future__ import annotations

from dataclasses import replace
import unittest

from core.providers.agentic_models import codex_routing_constraint, codex_runtime_policy
from core.providers.agentic_protocol import (
    AgenticModelRequest,
    AgenticRequestContentBlock,
    AgenticUsage,
)
from core.runtime.hosted_agentic_budget import HostedAgenticBudget
from core.runtime.hosted_agentic_models import HostedAgenticLoopError


class HostedAgenticBudgetTest(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = replace(
            codex_runtime_policy(),
            max_steps_per_turn=1,
            max_tool_calls_per_turn=1,
            max_wall_time_seconds=2,
            max_tool_result_bytes=8,
            max_total_tool_result_bytes=8,
            max_input_tokens=10,
            max_output_tokens=5,
        )
        self.request = AgenticModelRequest(
            schema_version="1",
            request_id="request-1",
            correlation_id="turn-1",
            model_id="fake-model",
            reasoning_effort=None,
            content_blocks=(
                AgenticRequestContentBlock(
                    content_block_id="block-1",
                    role="user",
                    data_class="public",
                    provenance="user_input",
                    trust_level="trusted_actor",
                    content_type="text/plain",
                    content=b"12345678",
                ),
            ),
            tool_definitions=(),
            tool_results=(),
            provider_private_state=None,
            routing_constraint=codex_routing_constraint(),
            max_output_tokens=5,
        )

    def test_step_and_wall_time_limits_are_hard(self) -> None:
        clock = _Clock()
        budget = HostedAgenticBudget(self.policy, monotonic=clock)
        budget.begin_step(self.request, None)

        with self.assertRaisesRegex(HostedAgenticLoopError, "step_limit"):
            budget.begin_step(self.request, None)
        clock.value = 3
        with self.assertRaisesRegex(HostedAgenticLoopError, "time_limit"):
            budget.check_time()

    def test_cost_ceiling_requires_an_upper_bound_before_request(self) -> None:
        budget = HostedAgenticBudget(
            replace(self.policy, max_estimated_cost_microusd=0)
        )

        with self.assertRaisesRegex(HostedAgenticLoopError, "estimate_unavailable"):
            budget.begin_step(self.request, None)
        with self.assertRaisesRegex(HostedAgenticLoopError, "cost_limit"):
            budget.begin_step(self.request, 1)
        with self.assertRaisesRegex(HostedAgenticLoopError, "estimate_unavailable"):
            budget.begin_step(self.request, -1)

    def test_reported_usage_replaces_each_active_request_reservation(self) -> None:
        budget = HostedAgenticBudget(
            replace(
                self.policy,
                max_steps_per_turn=3,
                max_estimated_cost_microusd=250,
            )
        )

        budget.begin_step(self.request, 125)
        budget.add_usage(
            AgenticUsage(
                input_tokens=1,
                output_tokens=1,
                estimated_cost_microusd=5,
            )
        )
        budget.begin_step(self.request, 125)
        budget.add_usage(
            AgenticUsage(
                input_tokens=1,
                output_tokens=1,
                estimated_cost_microusd=5,
            )
        )
        budget.begin_step(self.request, 125)

        self.assertEqual(budget.estimated_cost_microusd, 135)
        self.assertEqual(budget.reported_cost_microusd, 10)

    def test_missing_usage_keeps_worst_case_request_reservations(self) -> None:
        budget = HostedAgenticBudget(
            replace(
                self.policy,
                max_steps_per_turn=3,
                max_estimated_cost_microusd=250,
            )
        )

        budget.begin_step(self.request, 125)
        budget.begin_step(self.request, 125)

        with self.assertRaisesRegex(HostedAgenticLoopError, "cost_limit"):
            budget.begin_step(self.request, 125)

    def test_later_cost_ceiling_sees_usage_recorded_without_an_initial_ceiling(self) -> None:
        initial = replace(
            self.policy,
            max_steps_per_turn=2,
            max_estimated_cost_microusd=None,
        )
        budget = HostedAgenticBudget(initial)
        budget.begin_step(self.request, 125)
        budget.add_usage(
            AgenticUsage(
                input_tokens=1,
                output_tokens=1,
                estimated_cost_microusd=5,
            )
        )

        with self.assertRaisesRegex(HostedAgenticLoopError, "cost_limit"):
            budget.tighten(replace(initial, max_estimated_cost_microusd=4))

    def test_usage_and_total_tool_result_limits_are_cumulative(self) -> None:
        budget = HostedAgenticBudget(self.policy)
        budget.add_usage(AgenticUsage(input_tokens=6, output_tokens=3))

        with self.assertRaisesRegex(HostedAgenticLoopError, "output_token_limit"):
            budget.add_usage(AgenticUsage(input_tokens=1, output_tokens=3))
        budget.add_tool_result(8)
        with self.assertRaisesRegex(HostedAgenticLoopError, "tool_result_limit"):
            budget.add_tool_result(1)

    def test_streamed_output_is_bounded_before_provider_usage_arrives(self) -> None:
        budget = HostedAgenticBudget(self.policy)
        budget.add_output_chunk("x" * 160)

        with self.assertRaisesRegex(HostedAgenticLoopError, "output_token_limit"):
            budget.add_output_chunk("x")

    def test_live_policy_can_only_tighten_remaining_budget(self) -> None:
        initial = replace(self.policy, max_tool_calls_per_turn=4)
        budget = HostedAgenticBudget(initial)
        budget.add_tool_call()
        budget.add_tool_call()

        with self.assertRaisesRegex(HostedAgenticLoopError, "tool_call_limit"):
            budget.tighten(replace(initial, max_tool_calls_per_turn=1))


class _Clock:
    value = 0.0

    def __call__(self) -> float:
        return self.value


if __name__ == "__main__":
    unittest.main()
