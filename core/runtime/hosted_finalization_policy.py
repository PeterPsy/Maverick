"""Price- and recipe-derived terminal reserves, never provider-name constants."""

import math

from core.providers.errors import AgenticProfileError
from core.runtime.hosted_agentic_models import HostedFinalizationPolicy


def provider_finalization_policy(config, recipe) -> HostedFinalizationPolicy:
    """Cover every request admitted by the recipe's input-byte token bound.

    Core input admission uses ceil(bytes / 4); provider request reservation may
    use a different bytes/token assumption. Convert that bound before pricing
    so the reserve cannot be smaller than the actual request estimator.
    """
    output_tokens = min(2_048, recipe.support_flags.output_token_limit)
    input_limit = min(recipe.context_policy.max_request_input_tokens, recipe.support_flags.input_token_limit)
    pricing = config.token_cost_policy
    input_tokens = math.ceil(4 * input_limit / pricing.estimated_input_bytes_per_token)
    return HostedFinalizationPolicy(
        exploration_max_output_tokens=output_tokens,
        finalization_max_output_tokens=output_tokens,
        finalization_cost_reserve_microusd_per_attempt=pricing.usage_cost_microusd(input_tokens, output_tokens),
        finalization_time_reserve_seconds_per_attempt=20.0,
        max_recovery_attempts=1,
    )


def validate_finalization_resources(policy, reserve) -> None:
    if (
        policy.max_estimated_cost_microusd is None
        or policy.max_estimated_cost_microusd < reserve.reserved_cost_microusd
        or policy.max_steps_per_turn < reserve.reserved_provider_steps
        or policy.max_output_tokens < reserve.reserved_output_tokens
        or policy.max_wall_time_seconds < reserve.reserved_time_seconds
    ):
        raise AgenticProfileError("maverick_profile_finalization_budget_insufficient")


__all__ = ["provider_finalization_policy", "validate_finalization_resources"]
