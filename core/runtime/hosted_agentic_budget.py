"""Hard budget accounting for one hosted agentic turn."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import time
from typing import Callable

from core.providers.agentic_models import AgenticRuntimePolicy
from core.providers.agentic_protocol import AgenticModelRequest, AgenticUsage
from core.runtime.authority import intersect_runtime_policies
from core.runtime.hosted_agentic_models import HostedAgenticLoopError


@dataclass
class HostedAgenticBudget:
    policy: AgenticRuntimePolicy
    monotonic: Callable[[], float] = time.monotonic
    steps: int = 0
    tool_calls: int = 0
    total_tool_result_bytes: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    streamed_output_bytes: int = 0
    estimated_cost_microusd: int = 0
    reported_cost_microusd: int = 0
    started_at: float = field(init=False)

    def __post_init__(self) -> None:
        self.started_at = self.monotonic()

    def begin_step(self, request: AgenticModelRequest, estimated_cost: int | None) -> None:
        self.check_time()
        if self.steps >= self.policy.max_steps_per_turn:
            raise HostedAgenticLoopError("agent_step_limit_reached")
        estimated_input = _estimate_request_tokens(request)
        if self.input_tokens + estimated_input > self.policy.max_input_tokens:
            raise HostedAgenticLoopError("agent_input_token_limit_reached")
        ceiling = self.policy.max_estimated_cost_microusd
        if ceiling is not None:
            if estimated_cost is None:
                raise HostedAgenticLoopError("agent_cost_estimate_unavailable")
            if self.estimated_cost_microusd + estimated_cost > ceiling:
                raise HostedAgenticLoopError("agent_cost_limit_reached")
            self.estimated_cost_microusd += estimated_cost
        self.steps += 1

    def add_tool_call(self) -> None:
        self.check_time()
        if self.tool_calls >= self.policy.max_tool_calls_per_turn:
            raise HostedAgenticLoopError("agent_tool_call_limit_reached")
        self.tool_calls += 1

    def add_tool_result(self, size_bytes: int) -> None:
        self.total_tool_result_bytes += size_bytes
        if self.total_tool_result_bytes > self.policy.max_total_tool_result_bytes:
            raise HostedAgenticLoopError("agent_tool_result_limit_reached")

    def add_output_chunk(self, text: str) -> None:
        """Bound decoded output even when a provider delays or omits usage."""
        self.streamed_output_bytes += len(text.encode("utf-8"))
        if self.streamed_output_bytes > self.policy.max_output_tokens * 32:
            raise HostedAgenticLoopError("agent_output_token_limit_reached")

    def add_usage(self, usage: AgenticUsage) -> None:
        if min(usage.input_tokens, usage.output_tokens) < 0:
            raise HostedAgenticLoopError("provider_response_invalid")
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        if self.input_tokens > self.policy.max_input_tokens:
            raise HostedAgenticLoopError("agent_input_token_limit_reached")
        if self.output_tokens > self.policy.max_output_tokens:
            raise HostedAgenticLoopError("agent_output_token_limit_reached")
        if self.streamed_output_bytes > self.policy.max_output_tokens * 32:
            raise HostedAgenticLoopError("agent_output_token_limit_reached")
        if usage.estimated_cost_microusd is not None and usage.estimated_cost_microusd < 0:
            raise HostedAgenticLoopError("provider_response_invalid")
        if usage.estimated_cost_microusd is not None:
            self.reported_cost_microusd += usage.estimated_cost_microusd
            ceiling = self.policy.max_estimated_cost_microusd
            if ceiling is not None and self.reported_cost_microusd > ceiling:
                raise HostedAgenticLoopError("agent_cost_limit_reached")

    def tighten(self, policy: AgenticRuntimePolicy) -> None:
        """Apply live restrictions without ever loosening the turn budget."""
        self.policy = intersect_runtime_policies(self.policy, policy)
        self.check_time()
        if self.steps > self.policy.max_steps_per_turn:
            raise HostedAgenticLoopError("agent_step_limit_reached")
        if self.tool_calls > self.policy.max_tool_calls_per_turn:
            raise HostedAgenticLoopError("agent_tool_call_limit_reached")
        if self.total_tool_result_bytes > self.policy.max_total_tool_result_bytes:
            raise HostedAgenticLoopError("agent_tool_result_limit_reached")
        if self.input_tokens > self.policy.max_input_tokens:
            raise HostedAgenticLoopError("agent_input_token_limit_reached")
        if self.output_tokens > self.policy.max_output_tokens:
            raise HostedAgenticLoopError("agent_output_token_limit_reached")

    def check_time(self) -> None:
        if self.monotonic() - self.started_at > self.policy.max_wall_time_seconds:
            raise HostedAgenticLoopError("agent_time_limit_reached")


def _estimate_request_tokens(request: AgenticModelRequest) -> int:
    byte_count = sum(len(block.content) for block in request.content_blocks)
    byte_count += sum(len(result.content) for result in request.tool_results)
    byte_count += sum(
        len(tool.name) + len(tool.description) + len(str(tool.input_schema))
        for tool in request.tool_definitions
    )
    if request.provider_private_state is not None:
        byte_count += len(request.provider_private_state.content)
    return max(1, math.ceil(byte_count / 4))
