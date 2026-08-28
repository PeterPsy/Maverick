from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
import unittest

from core.providers.agentic_models import codex_routing_constraint, codex_runtime_policy
from core.providers.agentic_protocol import (
    AgenticModelRequest,
    AgenticProviderPrivateState,
    AgenticRequestContentBlock,
    AgenticToolResult,
    AgenticUsage,
)
from core.providers.google_agentic_profile import (
    google_agentic_preview_policy,
    google_interactions_routing_constraint,
)
from core.providers.google_interactions_client import (
    google_36_flash_request_ceiling_microusd,
)
from core.providers.openrouter_agentic_client import (
    openrouter_deepinfra_v4_flash_request_ceiling_microusd,
)
from core.providers.openrouter_agentic_profile import (
    openrouter_agentic_preview_policy,
    openrouter_agentic_routing_constraint,
)
from core.runtime.hosted_agentic_budget import HostedAgenticBudget
from core.runtime.hosted_agentic_models import (
    HostedAgenticLoopError,
    HostedFinalizationPolicy,
)
from core.runtime.hosted_provider_runtime import (
    GOOGLE_HOSTED_FINALIZATION_POLICY,
    OPENROUTER_HOSTED_FINALIZATION_POLICY,
)


class HostedAgenticBudgetTest(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = replace(
            codex_runtime_policy(),
            max_steps_per_turn=4,
            max_tool_calls_per_turn=2,
            max_wall_time_seconds=4,
            max_tool_result_bytes=8,
            max_total_tool_result_bytes=8,
            max_input_tokens=50,
            max_output_tokens=20,
            max_estimated_cost_microusd=100,
        )
        self.finalization_policy = HostedFinalizationPolicy(
            exploration_max_output_tokens=5,
            finalization_max_output_tokens=5,
            finalization_cost_reserve_microusd_per_attempt=10,
            finalization_time_reserve_seconds_per_attempt=1,
            max_recovery_attempts=1,
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
            request_phase="exploration",
        )

    def budget(self, policy=None, *, clock=None) -> HostedAgenticBudget:
        return HostedAgenticBudget(
            policy or self.policy,
            self.finalization_policy,
            monotonic=clock or _Clock(),
        )

    def phased_request(self, phase: str) -> AgenticModelRequest:
        return replace(self.request, request_phase=phase)

    def test_production_profiles_cover_both_pinned_finalization_attempts(self) -> None:
        for policy, finalization in (
            (google_agentic_preview_policy(), GOOGLE_HOSTED_FINALIZATION_POLICY),
            (
                openrouter_agentic_preview_policy(),
                OPENROUTER_HOSTED_FINALIZATION_POLICY,
            ),
        ):
            with self.subTest(policy=policy):
                self.assertGreaterEqual(
                    policy.max_steps_per_turn,
                    finalization.reserved_provider_steps,
                )
                self.assertGreaterEqual(
                    policy.max_output_tokens,
                    finalization.reserved_output_tokens,
                )
                self.assertGreaterEqual(
                    policy.max_estimated_cost_microusd,
                    finalization.reserved_cost_microusd,
                )
                self.assertGreaterEqual(
                    policy.max_wall_time_seconds,
                    finalization.reserved_time_seconds,
                )

    def test_production_cost_reserves_cover_a_maximum_allowed_tool_result(self) -> None:
        cases = (
            (
                google_agentic_preview_policy(),
                GOOGLE_HOSTED_FINALIZATION_POLICY,
                google_interactions_routing_constraint(),
                google_36_flash_request_ceiling_microusd,
                False,
            ),
            (
                openrouter_agentic_preview_policy(),
                OPENROUTER_HOSTED_FINALIZATION_POLICY,
                openrouter_agentic_routing_constraint(),
                openrouter_deepinfra_v4_flash_request_ceiling_microusd,
                True,
            ),
        )
        for (
            policy,
            finalization,
            routing,
            estimator,
            carries_prior_result,
        ) in cases:
            with self.subTest(routing=routing.endpoint_id):
                prefix = b'{"value":"'
                suffix = b'"}'
                maximum_result = (
                    prefix
                    + b"x"
                    * (policy.max_tool_result_bytes - len(prefix) - len(suffix))
                    + suffix
                )
                request = replace(
                    self.request,
                    routing_constraint=routing,
                    request_phase="finalization",
                    max_output_tokens=finalization.finalization_max_output_tokens,
                    provider_private_state=(
                        AgenticProviderPrivateState(
                            codec_id="fixture-codec",
                            codec_version="1",
                            schema_version="1",
                            content_type="application/json",
                            content=b"x" * policy.max_tool_result_bytes,
                        )
                        if carries_prior_result
                        else None
                    ),
                    tool_results=(
                        AgenticToolResult(
                            provider_tool_call_id="call-max-result",
                            provider_tool_name="fixture_read",
                            content_type="application/json",
                            content=maximum_result,
                            is_error=False,
                        ),
                    ),
                )

                self.assertLessEqual(
                    estimator(request),
                    finalization.finalization_cost_reserve_microusd_per_attempt,
                )
                self.assertLessEqual(
                    finalization.reserved_cost_microusd,
                    policy.max_estimated_cost_microusd,
                )

    def test_provider_steps_and_tool_calls_are_separate_budgets(self) -> None:
        budget = self.budget()

        self.assertEqual(
            budget.select_phase(pairing_source=None, existing_records=()),
            "exploration",
        )
        reservation = budget.begin_step(self.request, 10, phase="exploration")
        self.assertTrue(reservation.snapshot.finalization_reserved)
        budget.add_tool_call()
        budget.add_usage(AgenticUsage(input_tokens=1, output_tokens=1, estimated_cost_microusd=1))
        budget.complete_step()

        budget.add_tool_call()
        self.assertEqual(budget.steps, 1)
        self.assertEqual(budget.tool_calls, 2)
        self.assertEqual(
            budget.select_phase(pairing_source=None, existing_records=()),
            "finalization",
        )

    def test_public_snapshot_exposes_every_finalization_control_without_content(self) -> None:
        payload = self.budget().snapshot().public_payload()

        self.assertEqual(
            set(payload),
            {
                "remaining_provider_steps",
                "remaining_tool_calls",
                "remaining_output_tokens",
                "remaining_cost_microusd",
                "remaining_wall_time_seconds",
                "finalization_reserved",
            },
        )
        self.assertTrue(payload["finalization_reserved"])

    def test_step_and_reserved_deadline_limits_are_hard(self) -> None:
        clock = _Clock()
        budget = self.budget(clock=clock)
        budget.begin_step(self.request, 10, phase="exploration")

        clock.value = 2.01
        with self.assertRaisesRegex(
            HostedAgenticLoopError,
            "agent_finalization_time_reserve_reached",
        ):
            budget.check_time()

        final_budget = self.budget(
            replace(self.policy, max_steps_per_turn=2),
        )
        final_budget.begin_step(
            self.phased_request("finalization"),
            10,
            phase="finalization",
        )
        final_budget.complete_step()
        final_budget.begin_step(
            self.phased_request("finalization_recovery"),
            10,
            phase="finalization_recovery",
        )
        final_budget.complete_step()
        with self.assertRaisesRegex(HostedAgenticLoopError, "reserve_unavailable"):
            final_budget.plan_step("finalization_recovery")

    def test_cost_ceiling_requires_an_upper_bound_before_request(self) -> None:
        budget = self.budget()

        with self.assertRaisesRegex(HostedAgenticLoopError, "estimate_unavailable"):
            budget.begin_step(self.request, None, phase="exploration")
        with self.assertRaisesRegex(HostedAgenticLoopError, "estimate_unavailable"):
            budget.begin_step(self.request, -1, phase="exploration")

        unbounded = self.budget(
            replace(self.policy, max_estimated_cost_microusd=None),
        )
        with self.assertRaisesRegex(HostedAgenticLoopError, "reserve_unavailable"):
            unbounded.plan_step("exploration")

    def test_reported_usage_replaces_active_request_reservations(self) -> None:
        budget = self.budget()

        budget.begin_step(self.request, 20, phase="exploration")
        budget.add_usage(
            AgenticUsage(
                input_tokens=1,
                output_tokens=1,
                estimated_cost_microusd=5,
            )
        )
        budget.complete_step()
        budget.begin_step(self.request, 20, phase="exploration")

        self.assertEqual(budget.estimated_cost_microusd, 25)
        self.assertEqual(budget.reported_cost_microusd, 5)
        self.assertEqual(budget.accounted_output_tokens, 6)

    def test_missing_usage_keeps_worst_case_request_reservations(self) -> None:
        budget = self.budget(
            replace(self.policy, max_estimated_cost_microusd=60)
        )

        budget.begin_step(self.request, 20, phase="exploration")
        budget.complete_step()
        budget.begin_step(self.request, 20, phase="exploration")
        budget.complete_step()

        with self.assertRaisesRegex(HostedAgenticLoopError, "reserve_unavailable"):
            budget.begin_step(
                self.phased_request("finalization"),
                11,
                phase="finalization",
            )
        budget.begin_step(
            self.phased_request("finalization"),
            10,
            phase="finalization",
        )

    def test_later_cost_ceiling_sees_usage_recorded_without_initial_ceiling(self) -> None:
        no_cost_reserve = replace(
            self.finalization_policy,
            finalization_cost_reserve_microusd_per_attempt=0,
        )
        initial = replace(self.policy, max_estimated_cost_microusd=None)
        budget = HostedAgenticBudget(initial, no_cost_reserve, monotonic=_Clock())
        budget.begin_step(self.request, 20, phase="exploration")
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
        budget = self.budget(replace(self.policy, max_output_tokens=5))
        budget.add_usage(AgenticUsage(input_tokens=6, output_tokens=3))

        with self.assertRaisesRegex(HostedAgenticLoopError, "output_token_limit"):
            budget.add_usage(AgenticUsage(input_tokens=1, output_tokens=3))
        budget.add_tool_result(8)
        with self.assertRaisesRegex(HostedAgenticLoopError, "tool_result_limit"):
            budget.add_tool_result(1)

    def test_streamed_output_is_bounded_before_provider_usage_arrives(self) -> None:
        budget = self.budget()
        budget.begin_step(self.request, 10, phase="exploration")
        budget.add_output_chunk("x" * 160)

        with self.assertRaisesRegex(HostedAgenticLoopError, "output_token_limit"):
            budget.add_output_chunk("x")

    def test_live_policy_can_only_tighten_remaining_budget(self) -> None:
        budget = self.budget(replace(self.policy, max_tool_calls_per_turn=4))
        budget.add_tool_call()
        budget.add_tool_call()

        with self.assertRaisesRegex(HostedAgenticLoopError, "tool_call_limit"):
            budget.tighten(replace(self.policy, max_tool_calls_per_turn=1))

    def test_finalization_attempt_requires_full_output_cost_and_time_reserve(self) -> None:
        request = self.phased_request("finalization")
        for policy in (
            replace(self.policy, max_output_tokens=9),
            replace(self.policy, max_estimated_cost_microusd=19),
            replace(self.policy, max_wall_time_seconds=1.9),
        ):
            with self.subTest(policy=policy):
                budget = self.budget(policy)
                with self.assertRaisesRegex(
                    HostedAgenticLoopError,
                    "reserve_unavailable",
                ):
                    budget.begin_step(request, 10, phase="finalization")

        with self.assertRaisesRegex(
            HostedAgenticLoopError,
            "reserve_unavailable",
        ):
            self.budget().begin_step(request, 11, phase="finalization")

    def test_provider_cost_cannot_exceed_preflight_ceiling(self) -> None:
        budget = self.budget()
        budget.begin_step(self.request, 10, phase="exploration")

        with self.assertRaisesRegex(
            HostedAgenticLoopError,
            "provider_response_invalid",
        ):
            budget.add_usage(
                AgenticUsage(
                    input_tokens=1,
                    output_tokens=1,
                    estimated_cost_microusd=11,
                )
            )

        self.assertEqual(budget.input_tokens, 0)
        self.assertEqual(budget.output_tokens, 0)
        self.assertEqual(budget.estimated_cost_microusd, 10)

    def test_restart_restores_durable_step_tool_usage_and_result_accounting(self) -> None:
        records = (
            SimpleNamespace(
                budget_tool_call_charges=1,
                budget_tool_result_bytes=3,
                usage_report_count=1,
                usage_input_tokens=2,
                usage_output_tokens=1,
                usage_cost_microusd=4,
                budget_estimated_input_tokens=10,
                request_max_output_tokens=5,
                budget_estimated_cost_microusd=20,
            ),
            SimpleNamespace(
                budget_tool_call_charges=0,
                budget_tool_result_bytes=5,
                usage_report_count=0,
                budget_estimated_input_tokens=3,
                request_max_output_tokens=5,
                budget_estimated_cost_microusd=10,
            ),
        )
        budget = self.budget()

        budget.restore(records)

        self.assertEqual(budget.steps, 2)
        self.assertEqual(budget.tool_calls, 1)
        self.assertEqual(budget.total_tool_result_bytes, 8)
        self.assertEqual(budget.accounted_input_tokens, 5)
        self.assertEqual(budget.accounted_output_tokens, 6)
        self.assertEqual(budget.estimated_cost_microusd, 14)

    def test_restart_rejects_incoherent_durable_budget_accounting(self) -> None:
        record = SimpleNamespace(
            budget_tool_call_charges=2,
            observed_call_count=1,
            budget_tool_result_bytes=0,
            usage_report_count=0,
            usage_input_tokens=0,
            usage_output_tokens=0,
            usage_cost_microusd=None,
            budget_estimated_input_tokens=1,
            request_max_output_tokens=5,
            budget_estimated_cost_microusd=1,
        )

        with self.assertRaisesRegex(HostedAgenticLoopError, "provider_state_ambiguous"):
            self.budget().restore((record,))


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


if __name__ == "__main__":
    unittest.main()
