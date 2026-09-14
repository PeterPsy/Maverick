"""Focused concurrent executor for one hosted provider tool-call batch."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from core.providers.agentic_protocol import AgenticToolCall
from core.runtime.hosted_agentic_budget import HostedAgenticBudget
from core.runtime.hosted_agentic_models import HostedAgenticLoopError
from core.runtime.hosted_agentic_tool_execution import (
    execute_hosted_authorized_tool,
)
from core.runtime.runtime_cancellation import RuntimeCancellationSignal
from core.runtime.tool_orchestrator import RuntimeToolInvocationOutcome


@dataclass
class PreparedHostedToolCall:
    """Provider call plus its independently authorized runtime execution facts."""

    call: AgenticToolCall
    outcome: RuntimeToolInvocationOutcome
    orchestrator: object
    authority: object
    actor_context: object
    tool_policy: object


async def execute_hosted_tool_batch(
    prepared_calls: Sequence[PreparedHostedToolCall],
    execution_indexes: Sequence[int],
    *,
    budget: HostedAgenticBudget,
    cancellation: RuntimeCancellationSignal,
    poll_seconds: float,
    terminalize: Callable[
        [object, RuntimeToolInvocationOutcome],
        RuntimeToolInvocationOutcome,
    ],
) -> None:
    """Execute every authorized call concurrently and isolate sibling failures."""
    if not execution_indexes:
        return
    results = await asyncio.gather(
        *(
            execute_hosted_authorized_tool(
                tool_orchestrator=prepared_calls[index].orchestrator,
                outcome=prepared_calls[index].outcome,
                authority=prepared_calls[index].authority,
                context=prepared_calls[index].actor_context,
                policy=prepared_calls[index].tool_policy,
                budget=budget,
                cancellation=cancellation,
                poll_seconds=poll_seconds,
            )
            for index in execution_indexes
        ),
        return_exceptions=True,
    )
    for index, result in zip(execution_indexes, results, strict=True):
        if isinstance(result, BaseException):
            if isinstance(result, asyncio.CancelledError):
                raise result
            if (
                isinstance(result, HostedAgenticLoopError)
                and result.reason_code == "runtime_cancelled"
            ):
                raise result
            result = terminalize(
                prepared_calls[index].orchestrator,
                prepared_calls[index].outcome,
            )
        prepared_calls[index].outcome = result


__all__ = ["PreparedHostedToolCall", "execute_hosted_tool_batch"]
