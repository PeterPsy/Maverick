"""Public snapshots and reservations produced by the hosted budget controller."""

from __future__ import annotations

from dataclasses import dataclass

from core.runtime.hosted_agentic_models import HostedAgenticRequestPhase


@dataclass(frozen=True)
class HostedAgenticBudgetSnapshot:
    remaining_provider_steps: int
    remaining_tool_calls: int
    remaining_output_tokens: int
    remaining_cost_microusd: int | None
    remaining_wall_time_seconds: float
    finalization_reserved: bool

    def public_payload(self) -> dict[str, object]:
        return {
            "remaining_provider_steps": self.remaining_provider_steps,
            "remaining_tool_calls": self.remaining_tool_calls,
            "remaining_output_tokens": self.remaining_output_tokens,
            "remaining_cost_microusd": self.remaining_cost_microusd,
            "remaining_wall_time_seconds": round(
                max(0.0, self.remaining_wall_time_seconds),
                3,
            ),
            "finalization_reserved": self.finalization_reserved,
        }


@dataclass(frozen=True)
class HostedAgenticStepPlan:
    phase: HostedAgenticRequestPhase
    max_output_tokens: int
    future_finalization_attempts: int
    deadline: float


@dataclass(frozen=True)
class HostedAgenticStepReservation:
    phase: HostedAgenticRequestPhase
    estimated_input_tokens: int
    estimated_cost_microusd: int | None
    snapshot: HostedAgenticBudgetSnapshot
