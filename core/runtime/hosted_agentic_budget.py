"""Durable hard-budget and finalization-reserve accounting for hosted turns."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import time
from typing import Callable, Iterable

from core.providers.agentic_models import AgenticRuntimePolicy
from core.providers.agentic_protocol import AgenticModelRequest, AgenticUsage
from core.runtime.authority import intersect_runtime_policies
from core.runtime.hosted_agentic_budget_models import (
    HostedAgenticBudgetSnapshot,
    HostedAgenticStepPlan,
    HostedAgenticStepReservation,
)
from core.runtime.hosted_agentic_budget_recovery import (
    restore_hosted_budget_accounting,
)
from core.runtime.hosted_agentic_finalization_budget import (
    hosted_budget_snapshot,
    plan_hosted_step,
    select_hosted_request_phase,
)
from core.runtime.hosted_agentic_models import (
    HostedAgenticLoopError,
    HostedAgenticRequestPhase,
    HostedFinalizationPolicy,
)


@dataclass
class HostedAgenticBudget:
    policy: AgenticRuntimePolicy
    finalization_policy: HostedFinalizationPolicy
    monotonic: Callable[[], float] = time.monotonic
    elapsed_seconds: float = 0.0
    steps: int = 0
    tool_calls: int = 0
    total_tool_result_bytes: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    streamed_output_bytes: int = 0
    estimated_cost_microusd: int = 0
    reported_cost_microusd: int = 0
    accounted_input_tokens: int = 0
    accounted_output_tokens: int = 0
    _active_input_reservation: int | None = field(default=None, init=False, repr=False)
    _active_output_reservation: int | None = field(default=None, init=False, repr=False)
    _active_cost_reservation: int | None = field(default=None, init=False, repr=False)
    _active_request_output_limit: int | None = field(default=None, init=False, repr=False)
    _active_streamed_output_bytes: int = field(default=0, init=False, repr=False)
    _active_deadline: float | None = field(default=None, init=False, repr=False)
    started_at: float = field(init=False)

    def __post_init__(self) -> None:
        elapsed = float(self.elapsed_seconds)
        if not math.isfinite(elapsed):
            raise ValueError("Hosted budget elapsed time must be finite.")
        elapsed = max(0.0, elapsed)
        self.started_at = self.monotonic() - elapsed

    def restore(self, records: Iterable[object]) -> None:
        """Rebuild conservative accounting from immutable request reservations."""
        if any(
            (
                self.steps,
                self.tool_calls,
                self.total_tool_result_bytes,
                self.input_tokens,
                self.output_tokens,
                self.streamed_output_bytes,
                self.reported_cost_microusd,
                self.accounted_input_tokens,
                self.accounted_output_tokens,
                self.estimated_cost_microusd,
            )
        ):
            raise ValueError("Hosted budget restoration requires a fresh budget.")
        restored = restore_hosted_budget_accounting(
            records,
            finite_cost_required=(
                self.policy.max_estimated_cost_microusd is not None
            ),
        )
        self.steps = restored.steps
        self.tool_calls = restored.tool_calls
        self.total_tool_result_bytes = restored.total_tool_result_bytes
        self.input_tokens = restored.input_tokens
        self.output_tokens = restored.output_tokens
        self.reported_cost_microusd = restored.reported_cost_microusd
        self.accounted_input_tokens = restored.accounted_input_tokens
        self.accounted_output_tokens = restored.accounted_output_tokens
        self.estimated_cost_microusd = restored.estimated_cost_microusd
        self._validate_accounting()

    def select_phase(
        self,
        *,
        pairing_source: object | None,
        existing_records: Iterable[object],
    ) -> HostedAgenticRequestPhase:
        return select_hosted_request_phase(
            self,
            pairing_source=pairing_source,
            existing_records=existing_records,
        )

    def plan_step(self, phase: HostedAgenticRequestPhase) -> HostedAgenticStepPlan:
        return plan_hosted_step(self, phase)

    def begin_step(
        self,
        request: AgenticModelRequest,
        estimated_cost: int | None,
        *,
        phase: HostedAgenticRequestPhase,
    ) -> HostedAgenticStepReservation:
        plan = self.plan_step(phase)
        if (
            request.request_phase != phase
            or request.max_output_tokens < 1
            or request.max_output_tokens > plan.max_output_tokens
        ):
            raise HostedAgenticLoopError("agent_finalization_reserve_violation")
        if self.monotonic() > plan.deadline:
            raise HostedAgenticLoopError("agent_finalization_reserve_unavailable")
        estimated_input = estimate_hosted_request_tokens(request)
        if self.accounted_input_tokens + estimated_input > self.policy.max_input_tokens:
            raise HostedAgenticLoopError("agent_input_token_limit_reached")
        ceiling = self.policy.max_estimated_cost_microusd
        if estimated_cost is not None and estimated_cost < 0:
            raise HostedAgenticLoopError("agent_cost_estimate_unavailable")
        if ceiling is not None and estimated_cost is None:
            raise HostedAgenticLoopError("agent_cost_estimate_unavailable")
        finalization_cost_reserve = (
            self.finalization_policy.finalization_cost_reserve_microusd_per_attempt
        )
        if (
            phase != "exploration"
            and finalization_cost_reserve > 0
            and estimated_cost is not None
            and estimated_cost > finalization_cost_reserve
        ):
            raise HostedAgenticLoopError("agent_finalization_reserve_unavailable")
        protected_cost = (
            plan.future_finalization_attempts
            * self.finalization_policy.finalization_cost_reserve_microusd_per_attempt
        )
        if estimated_cost is not None and ceiling is not None:
            projected_cost = self.estimated_cost_microusd + estimated_cost
            if projected_cost > ceiling:
                raise HostedAgenticLoopError("agent_cost_limit_reached")
            if projected_cost > ceiling - protected_cost:
                raise HostedAgenticLoopError(
                    "agent_finalization_reserve_unavailable"
                )
        self.steps += 1
        self.accounted_input_tokens += estimated_input
        self.accounted_output_tokens += request.max_output_tokens
        self._active_input_reservation = estimated_input
        self._active_output_reservation = request.max_output_tokens
        self._active_request_output_limit = request.max_output_tokens
        self._active_streamed_output_bytes = 0
        self._active_deadline = plan.deadline
        if estimated_cost is not None:
            self.estimated_cost_microusd += estimated_cost
            self._active_cost_reservation = estimated_cost
        snapshot = self.snapshot(
            future_finalization_attempts=plan.future_finalization_attempts
        )
        return HostedAgenticStepReservation(
            phase=phase,
            estimated_input_tokens=estimated_input,
            estimated_cost_microusd=estimated_cost,
            snapshot=snapshot,
        )

    def complete_step(self) -> None:
        """Keep missing-usage reservations but close the active deadline."""
        self._active_input_reservation = None
        self._active_output_reservation = None
        self._active_cost_reservation = None
        self._active_request_output_limit = None
        self._active_streamed_output_bytes = 0
        self._active_deadline = None

    def check_tool_call(self) -> None:
        self.check_time()
        if self.tool_calls >= self.policy.max_tool_calls_per_turn:
            raise HostedAgenticLoopError("agent_tool_call_limit_reached")

    def add_tool_call(self) -> None:
        self.check_tool_call()
        self.tool_calls += 1

    def require_finalization_reserve(self) -> None:
        """Fail closed if live policy/time drift consumed the protected reserve."""
        if not self.snapshot().finalization_reserved:
            raise HostedAgenticLoopError("agent_finalization_reserve_unavailable")

    def tool_execution_deadline(self, *, cleanup_seconds: float) -> float:
        """Return an active-step deadline that leaves time to persist tool pairing."""
        if (
            not isinstance(cleanup_seconds, (int, float))
            or isinstance(cleanup_seconds, bool)
            or not math.isfinite(cleanup_seconds)
            or cleanup_seconds < 0
            or self._active_deadline is None
        ):
            raise HostedAgenticLoopError("agent_finalization_reserve_unavailable")
        return self._active_deadline - cleanup_seconds

    def add_tool_result(self, size_bytes: int) -> None:
        if (
            not isinstance(size_bytes, int)
            or isinstance(size_bytes, bool)
            or size_bytes < 0
        ):
            raise HostedAgenticLoopError("provider_response_invalid")
        if size_bytes > self.policy.max_tool_result_bytes:
            raise HostedAgenticLoopError("agent_tool_result_limit_reached")
        projected = self.total_tool_result_bytes + size_bytes
        if projected > self.policy.max_total_tool_result_bytes:
            raise HostedAgenticLoopError("agent_tool_result_limit_reached")
        self.total_tool_result_bytes = projected

    def add_output_chunk(self, text: str) -> None:
        """Bound decoded output even when a provider omits usage."""
        size = len(text.encode("utf-8"))
        projected_total = self.streamed_output_bytes + size
        projected_active = self._active_streamed_output_bytes + size
        active_limit = self._active_request_output_limit
        if active_limit is not None and projected_active > active_limit * 32:
            raise HostedAgenticLoopError("agent_output_token_limit_reached")
        if projected_total > self.policy.max_output_tokens * 32:
            raise HostedAgenticLoopError("agent_output_token_limit_reached")
        self.streamed_output_bytes = projected_total
        self._active_streamed_output_bytes = projected_active

    def add_usage(self, usage: AgenticUsage) -> None:
        if any(
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
            for value in (usage.input_tokens, usage.output_tokens)
        ):
            raise HostedAgenticLoopError("provider_response_invalid")
        if (
            self._active_request_output_limit is not None
            and usage.output_tokens > self._active_request_output_limit
        ):
            raise HostedAgenticLoopError("agent_output_token_limit_reached")
        cost = usage.estimated_cost_microusd
        if cost is not None and (
            not isinstance(cost, int)
            or isinstance(cost, bool)
            or cost < 0
        ):
            raise HostedAgenticLoopError("provider_response_invalid")
        if (
            cost is not None
            and self._active_cost_reservation is not None
            and cost > self._active_cost_reservation
        ):
            raise HostedAgenticLoopError("provider_response_invalid")
        projected_input = (
            self.accounted_input_tokens
            - (self._active_input_reservation or 0)
            + usage.input_tokens
        )
        projected_output = (
            self.accounted_output_tokens
            - (self._active_output_reservation or 0)
            + usage.output_tokens
        )
        projected_cost = self.estimated_cost_microusd
        if cost is not None:
            projected_cost -= self._active_cost_reservation or 0
            projected_cost += cost
        if projected_input > self.policy.max_input_tokens:
            raise HostedAgenticLoopError("agent_input_token_limit_reached")
        if projected_output > self.policy.max_output_tokens:
            raise HostedAgenticLoopError("agent_output_token_limit_reached")
        ceiling = self.policy.max_estimated_cost_microusd
        if ceiling is not None and projected_cost > ceiling:
            raise HostedAgenticLoopError("agent_cost_limit_reached")
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        if self._active_input_reservation is not None:
            self.accounted_input_tokens -= self._active_input_reservation
            self._active_input_reservation = None
        if self._active_output_reservation is not None:
            self.accounted_output_tokens -= self._active_output_reservation
            self._active_output_reservation = None
        self.accounted_input_tokens += usage.input_tokens
        self.accounted_output_tokens += usage.output_tokens
        if cost is not None:
            self.reported_cost_microusd += cost
            if self._active_cost_reservation is not None:
                self.estimated_cost_microusd -= self._active_cost_reservation
                self._active_cost_reservation = None
            self.estimated_cost_microusd += cost
        self._validate_accounting()

    def tighten(self, policy: AgenticRuntimePolicy) -> None:
        """Apply live restrictions without ever loosening the turn budget."""
        self.policy = intersect_runtime_policies(self.policy, policy)
        self.check_time()
        self._validate_accounting()

    def snapshot(
        self,
        *,
        future_finalization_attempts: int | None = None,
    ) -> HostedAgenticBudgetSnapshot:
        return hosted_budget_snapshot(
            self,
            future_finalization_attempts=future_finalization_attempts,
        )

    @property
    def remaining_provider_steps(self) -> int:
        return max(0, self.policy.max_steps_per_turn - self.steps)

    @property
    def remaining_tool_calls(self) -> int:
        return max(0, self.policy.max_tool_calls_per_turn - self.tool_calls)

    @property
    def remaining_output_tokens(self) -> int:
        return max(0, self.policy.max_output_tokens - self.accounted_output_tokens)

    @property
    def remaining_cost_microusd(self) -> int | None:
        ceiling = self.policy.max_estimated_cost_microusd
        return (
            None
            if ceiling is None
            else max(0, ceiling - self.estimated_cost_microusd)
        )

    @property
    def remaining_wall_time_seconds(self) -> float:
        elapsed = self.monotonic() - self.started_at
        return max(0.0, self.policy.max_wall_time_seconds - elapsed)

    def check_time(self) -> None:
        now = self.monotonic()
        if self._active_deadline is not None and now > self._active_deadline:
            raise HostedAgenticLoopError("agent_finalization_time_reserve_reached")
        if now - self.started_at > self.policy.max_wall_time_seconds:
            raise HostedAgenticLoopError("agent_time_limit_reached")

    def _validate_accounting(self) -> None:
        if self.steps > self.policy.max_steps_per_turn:
            raise HostedAgenticLoopError("agent_step_limit_reached")
        if self.tool_calls > self.policy.max_tool_calls_per_turn:
            raise HostedAgenticLoopError("agent_tool_call_limit_reached")
        if self.total_tool_result_bytes > self.policy.max_total_tool_result_bytes:
            raise HostedAgenticLoopError("agent_tool_result_limit_reached")
        if self.accounted_input_tokens > self.policy.max_input_tokens:
            raise HostedAgenticLoopError("agent_input_token_limit_reached")
        if self.accounted_output_tokens > self.policy.max_output_tokens:
            raise HostedAgenticLoopError("agent_output_token_limit_reached")
        ceiling = self.policy.max_estimated_cost_microusd
        if ceiling is not None and self.estimated_cost_microusd > ceiling:
            raise HostedAgenticLoopError("agent_cost_limit_reached")


def estimate_hosted_request_tokens(request: AgenticModelRequest) -> int:
    byte_count = sum(len(block.content) for block in request.content_blocks)
    byte_count += sum(len(result.content) for result in request.tool_results)
    byte_count += sum(
        len(tool.name) + len(tool.description) + len(str(tool.input_schema))
        for tool in request.tool_definitions
    )
    if request.provider_private_state is not None:
        byte_count += len(request.provider_private_state.content)
    return max(1, math.ceil(byte_count / 4))
