"""Phase selection and protected terminal capacity for hosted turns."""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

from core.runtime.hosted_agentic_budget_models import (
    HostedAgenticBudgetSnapshot,
    HostedAgenticStepPlan,
)
from core.runtime.hosted_agentic_models import (
    HostedAgenticLoopError,
    HostedAgenticRequestPhase,
)

if TYPE_CHECKING:
    from core.runtime.hosted_agentic_budget import HostedAgenticBudget


def select_hosted_request_phase(
    budget: HostedAgenticBudget,
    *,
    pairing_source: object | None,
    existing_records: Iterable[object],
) -> HostedAgenticRequestPhase:
    """Choose exploration, reserved finalization, or its sole recovery."""
    budget.check_time()
    records = tuple(existing_records)
    invalid_final = next(
        (
            item
            for item in reversed(records)
            if getattr(item, "invalid_final_output", False)
        ),
        None,
    )
    if invalid_final is not None:
        raise HostedAgenticLoopError(
            getattr(
                invalid_final,
                "stream_failure_reason_code",
                "agent_final_output_empty",
            )
            or "agent_final_output_empty"
        )
    recovery_attempts = sum(
        getattr(item, "request_phase", "exploration")
        == "finalization_recovery"
        for item in records
    )
    source_phase = (
        None
        if pairing_source is None
        else getattr(pairing_source, "request_phase", "exploration")
    )
    if source_phase == "finalization_recovery":
        raise HostedAgenticLoopError("agent_finalization_recovery_exhausted")
    if source_phase == "finalization":
        if recovery_attempts >= budget.finalization_policy.max_recovery_attempts:
            raise HostedAgenticLoopError("agent_finalization_recovery_exhausted")
        return "finalization_recovery"
    if recovery_attempts:
        raise HostedAgenticLoopError("agent_finalization_recovery_exhausted")
    if _exploration_must_stop(budget):
        return "finalization"
    return "exploration"


def plan_hosted_step(
    budget: HostedAgenticBudget,
    phase: HostedAgenticRequestPhase,
) -> HostedAgenticStepPlan:
    """Fail before request construction if the phase cannot retain reserves."""
    future_attempts = _future_finalization_attempts(budget, phase)
    if budget.remaining_provider_steps < 1 + future_attempts:
        raise HostedAgenticLoopError("agent_finalization_reserve_unavailable")
    protected_output = (
        future_attempts
        * budget.finalization_policy.finalization_max_output_tokens
    )
    available_output = budget.remaining_output_tokens - protected_output
    output_ceiling = (
        budget.finalization_policy.exploration_max_output_tokens
        if phase == "exploration"
        else budget.finalization_policy.finalization_max_output_tokens
    )
    max_output_tokens = min(output_ceiling, available_output)
    if max_output_tokens < 1 or (
        phase != "exploration"
        and max_output_tokens
        < budget.finalization_policy.finalization_max_output_tokens
    ):
        raise HostedAgenticLoopError("agent_finalization_reserve_unavailable")
    cost_per_attempt = (
        budget.finalization_policy.finalization_cost_reserve_microusd_per_attempt
    )
    protected_cost = future_attempts * cost_per_attempt
    required_cost = protected_cost + (
        0 if phase == "exploration" else cost_per_attempt
    )
    remaining_cost = budget.remaining_cost_microusd
    if remaining_cost is None:
        if required_cost:
            raise HostedAgenticLoopError("agent_finalization_reserve_unavailable")
    elif remaining_cost < required_cost:
        raise HostedAgenticLoopError("agent_finalization_reserve_unavailable")
    time_per_attempt = (
        budget.finalization_policy.finalization_time_reserve_seconds_per_attempt
    )
    protected_time = future_attempts * time_per_attempt
    required_time = protected_time + (
        0.0 if phase == "exploration" else time_per_attempt
    )
    remaining_time = budget.remaining_wall_time_seconds
    if (
        phase == "exploration" and remaining_time <= protected_time
    ) or (
        phase != "exploration" and remaining_time < required_time
    ):
        raise HostedAgenticLoopError("agent_finalization_reserve_unavailable")
    return HostedAgenticStepPlan(
        phase=phase,
        max_output_tokens=max_output_tokens,
        future_finalization_attempts=future_attempts,
        deadline=(
            budget.started_at
            + budget.policy.max_wall_time_seconds
            - protected_time
        ),
    )


def hosted_budget_snapshot(
    budget: HostedAgenticBudget,
    *,
    future_finalization_attempts: int | None = None,
) -> HostedAgenticBudgetSnapshot:
    protected_attempts = (
        budget.finalization_policy.reserved_provider_steps
        if future_finalization_attempts is None
        else future_finalization_attempts
    )
    remaining_cost = budget.remaining_cost_microusd
    reserve_cost = (
        budget.finalization_policy.finalization_cost_reserve_microusd_per_attempt
    )
    reserved = (
        budget.remaining_provider_steps >= protected_attempts
        and budget.remaining_output_tokens
        >= protected_attempts
        * budget.finalization_policy.finalization_max_output_tokens
        and budget.remaining_wall_time_seconds
        >= protected_attempts
        * budget.finalization_policy.finalization_time_reserve_seconds_per_attempt
        and (
            (remaining_cost is None and reserve_cost == 0)
            or (
                remaining_cost is not None
                and remaining_cost >= protected_attempts * reserve_cost
            )
        )
    )
    return HostedAgenticBudgetSnapshot(
        remaining_provider_steps=budget.remaining_provider_steps,
        remaining_tool_calls=budget.remaining_tool_calls,
        remaining_output_tokens=budget.remaining_output_tokens,
        remaining_cost_microusd=remaining_cost,
        remaining_wall_time_seconds=budget.remaining_wall_time_seconds,
        finalization_reserved=reserved,
    )


def _exploration_must_stop(budget: HostedAgenticBudget) -> bool:
    reserve = budget.finalization_policy
    remaining_cost = budget.remaining_cost_microusd
    return (
        budget.remaining_tool_calls == 0
        or budget.remaining_provider_steps <= reserve.reserved_provider_steps
        or budget.remaining_output_tokens <= reserve.reserved_output_tokens
        or budget.remaining_wall_time_seconds <= reserve.reserved_time_seconds
        or (remaining_cost is None and reserve.reserved_cost_microusd > 0)
        or (
            remaining_cost is not None
            and remaining_cost <= reserve.reserved_cost_microusd
        )
    )


def _future_finalization_attempts(
    budget: HostedAgenticBudget,
    phase: HostedAgenticRequestPhase,
) -> int:
    if phase == "exploration":
        return budget.finalization_policy.reserved_provider_steps
    if phase == "finalization":
        return budget.finalization_policy.max_recovery_attempts
    if phase == "finalization_recovery":
        return 0
    raise HostedAgenticLoopError("agent_finalization_phase_invalid")
