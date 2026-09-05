from __future__ import annotations

from dataclasses import replace
import unittest

from core.providers.agentic_models import codex_routing_constraint, codex_runtime_policy
from core.providers.agentic_protocol import (
    AgenticModelRequest,
    AgenticRequestContentBlock,
    AgenticToolResult,
)
from core.providers.google_agentic_profile import (
    google_agentic_preview_policy,
    google_interactions_routing_constraint,
)
from core.providers.maverick_agent_builtins import (
    GOOGLE_INTERACTIONS_PROVIDER_CONFIG,
    OPENROUTER_DEEPINFRA_PROVIDER_CONFIG,
)
from core.providers.openrouter_agentic_state import (
    encode_openrouter_chat_state,
    initial_openrouter_chat_state,
)
from core.providers.openrouter_agentic_profile import (
    openrouter_agentic_preview_policy,
    openrouter_agentic_routing_constraint,
)
from core.runtime.hosted_agentic_budget import HostedAgenticBudget, estimate_hosted_request_tokens
from core.runtime.hosted_agentic_models import HostedFinalizationPolicy
from core.runtime.hosted_finalization_policy import provider_finalization_policy
from core.runtime.hosted_harness_recipes import (
    GOOGLE_GOVERNED_WORKSPACE_RECIPE, OPENROUTER_GOVERNED_WORKSPACE_RECIPE, hosted_full_context_policy,
)

GOOGLE_HOSTED_FINALIZATION_POLICY = provider_finalization_policy(GOOGLE_INTERACTIONS_PROVIDER_CONFIG, GOOGLE_GOVERNED_WORKSPACE_RECIPE)
OPENROUTER_HOSTED_FINALIZATION_POLICY = provider_finalization_policy(OPENROUTER_DEEPINFRA_PROVIDER_CONFIG, OPENROUTER_GOVERNED_WORKSPACE_RECIPE)


GOOGLE_REQUEST_COST_ESTIMATOR = (
    GOOGLE_INTERACTIONS_PROVIDER_CONFIG.token_cost_policy.request_ceiling_microusd
)
OPENROUTER_REQUEST_COST_ESTIMATOR = (
    OPENROUTER_DEEPINFRA_PROVIDER_CONFIG.token_cost_policy.request_ceiling_microusd
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

    def test_production_cost_reserves_cover_reachable_terminal_requests(self) -> None:
        cases = (
            (
                google_agentic_preview_policy(),
                GOOGLE_HOSTED_FINALIZATION_POLICY,
                google_interactions_routing_constraint(),
                GOOGLE_REQUEST_COST_ESTIMATOR,
                160_000,
                None,
            ),
            (
                openrouter_agentic_preview_policy(),
                OPENROUTER_HOSTED_FINALIZATION_POLICY,
                openrouter_agentic_routing_constraint(),
                OPENROUTER_REQUEST_COST_ESTIMATOR,
                250_000,
                encode_openrouter_chat_state(
                    replace(
                        initial_openrouter_chat_state(),
                        history=(
                            {"role": "user", "content": "x" * 250_000},
                        ),
                    )
                ),
            ),
        )
        for (
            policy,
            finalization,
            routing,
            estimator,
            context_bytes,
            provider_private_state,
        ) in cases:
            with self.subTest(routing=routing.endpoint_id):
                projected_result_limit = (
                    hosted_full_context_policy().tool_result_summary_bytes
                )
                prefix = b'{"value":"'
                suffix = b'"}'
                maximum_result = (
                    prefix
                    + b"x"
                    * (projected_result_limit - len(prefix) - len(suffix))
                    + suffix
                )
                exploration = replace(
                    self.request,
                    routing_constraint=routing,
                    content_blocks=(
                        replace(
                            self.request.content_blocks[0],
                            content=b"x" * context_bytes,
                        ),
                    ),
                    request_phase="exploration",
                    max_output_tokens=finalization.exploration_max_output_tokens,
                )
                request = replace(
                    exploration,
                    request_phase="finalization",
                    max_output_tokens=finalization.finalization_max_output_tokens,
                    provider_private_state=provider_private_state,
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
                budget = HostedAgenticBudget(
                    policy,
                    finalization,
                    monotonic=_Clock(),
                )
                budget.begin_step(
                    exploration,
                    estimator(exploration),
                    phase="exploration",
                )
                budget.complete_step()

                self.assertEqual(len(maximum_result), projected_result_limit)
                self.assertLessEqual(
                    estimator(request),
                    finalization.finalization_cost_reserve_microusd_per_attempt,
                )
                self.assertLessEqual(
                    budget.accounted_input_tokens
                    + estimate_hosted_request_tokens(request),
                    policy.max_input_tokens,
                )
                budget.begin_step(
                    request,
                    estimator(request),
                    phase="finalization",
                )
                maximal_request = replace(
                    request,
                    content_blocks=(
                        replace(
                            request.content_blocks[0],
                            content=(
                                b"x"
                                * (
                                    policy.max_input_tokens * 4
                                    - len(maximum_result)
                                )
                            ),
                        ),
                    ),
                    provider_private_state=None,
                )
                self.assertEqual(
                    estimate_hosted_request_tokens(maximal_request),
                    policy.max_input_tokens,
                )
                self.assertLessEqual(
                    estimator(maximal_request),
                    finalization.finalization_cost_reserve_microusd_per_attempt,
                )
                HostedAgenticBudget(
                    policy,
                    finalization,
                    monotonic=_Clock(),
                ).begin_step(
                    maximal_request,
                    estimator(maximal_request),
                    phase="finalization",
                )
                self.assertLessEqual(
                    finalization.reserved_cost_microusd,
                    policy.max_estimated_cost_microusd,
                )

    def test_data_driven_pricing_can_finalize_above_the_old_fixed_reserve(self) -> None:
        config = replace(OPENROUTER_DEEPINFRA_PROVIDER_CONFIG, token_cost_policy=replace(
            OPENROUTER_DEEPINFRA_PROVIDER_CONFIG.token_cost_policy,
            input_microusd_per_million_tokens=3_000_000,
            output_microusd_per_million_tokens=5_000_000,
        ))
        reserve = provider_finalization_policy(config, OPENROUTER_GOVERNED_WORKSPACE_RECIPE)
        policy = replace(openrouter_agentic_preview_policy(), max_estimated_cost_microusd=3_000_000)
        request = replace(self.request, request_phase="finalization", max_output_tokens=reserve.finalization_max_output_tokens,
                          content_blocks=(replace(self.request.content_blocks[0], content=b"x" * 100_002),))
        cost = config.token_cost_policy.request_ceiling_microusd(request)
        self.assertEqual(cost, 110_242)
        self.assertGreater(cost, 35_000)
        budget = HostedAgenticBudget(policy, reserve, monotonic=_Clock())
        budget.begin_step(request, cost, phase="finalization")
        self.assertEqual(budget.estimated_cost_microusd, cost)

    def test_onboarding_rejects_a_profile_that_cannot_fund_its_price_derived_reserve(self) -> None:
        from core.providers.errors import AgenticProfileError
        from core.runtime.hosted_finalization_policy import validate_finalization_resources

        config = replace(OPENROUTER_DEEPINFRA_PROVIDER_CONFIG, token_cost_policy=replace(
            OPENROUTER_DEEPINFRA_PROVIDER_CONFIG.token_cost_policy,
            input_microusd_per_million_tokens=3_000_000,
        ))
        with self.assertRaisesRegex(AgenticProfileError, "finalization_budget_insufficient"):
            validate_finalization_resources(openrouter_agentic_preview_policy(),
                                            provider_finalization_policy(config, OPENROUTER_GOVERNED_WORKSPACE_RECIPE))


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


if __name__ == "__main__":
    unittest.main()
