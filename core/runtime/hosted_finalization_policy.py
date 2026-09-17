"""Price- and model-config-derived terminal reserves."""

import math

from core.providers.errors import AgenticProfileError
from core.runtime.hosted_agentic_models import HostedFinalizationPolicy


HOSTED_PROVIDER_STEP_OUTPUT_TOKENS = 4_096


def provider_finalization_policy(config, model_config) -> HostedFinalizationPolicy:
    """Cover every request admitted by the model config's token bounds.

    Core input admission uses ceil(bytes / 4); provider request reservation may
    use a different bytes/token assumption. Convert that bound before pricing
    so the reserve cannot be smaller than the actual request estimator.
    """
    output_tokens = min(
        HOSTED_PROVIDER_STEP_OUTPUT_TOKENS,
        model_config.support_flags.output_token_limit,
    )
    input_limit = min(
        model_config.context_policy.max_request_input_tokens,
        model_config.support_flags.input_token_limit,
    )
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
        (
            policy.max_estimated_cost_microusd is not None
            and policy.max_estimated_cost_microusd
            < reserve.reserved_cost_microusd
        )
        or policy.max_steps_per_turn < reserve.reserved_provider_steps
        or policy.max_output_tokens < reserve.reserved_output_tokens
        or policy.max_wall_time_seconds < reserve.reserved_time_seconds
    ):
        raise AgenticProfileError("maverick_profile_finalization_budget_insufficient")


__all__ = [
    "HOSTED_PROVIDER_STEP_OUTPUT_TOKENS",
    "provider_finalization_policy",
    "validate_finalization_resources",
]
