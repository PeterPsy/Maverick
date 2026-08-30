"""Deadline-fenced execution of synchronous tools inside the hosted loop."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import uuid4

from core.runtime.authority import EffectiveRuntimeAuthority
from core.runtime.hosted_agentic_budget import HostedAgenticBudget
from core.runtime.hosted_agentic_models import (
    HostedAgenticLoopError,
    raise_if_hosted_cancelled,
)
from core.runtime.runtime_cancellation import RuntimeCancellationSignal
from core.runtime.tool_catalog import RuntimeToolActorContext
from core.runtime.tool_orchestrator import (
    RuntimeToolConfirmationPolicy,
    RuntimeToolExecutionControl,
    RuntimeToolInvocationOutcome,
    RuntimeToolOrchestrator,
)


_MAX_PAIRING_CLEANUP_SECONDS = 0.1
_CANCELLATION_QUIESCENT_TOOL_HANDLES = frozenset(
    {
        "core-capability:shell.run",
        "core-capability:process.start",
        "core-capability:process.status",
        "core-capability:process.input",
        "core-capability:process.interrupt",
    }
)


async def execute_hosted_authorized_tool(
    *,
    tool_orchestrator: RuntimeToolOrchestrator,
    outcome: RuntimeToolInvocationOutcome,
    authority: EffectiveRuntimeAuthority,
    context: RuntimeToolActorContext,
    policy: RuntimeToolConfirmationPolicy,
    budget: HostedAgenticBudget,
    cancellation: RuntimeCancellationSignal,
    poll_seconds: float,
) -> RuntimeToolInvocationOutcome:
    """Run synchronous tool code without allowing it to consume terminal time."""
    raise_if_hosted_cancelled(cancellation)
    cleanup_seconds = min(
        _MAX_PAIRING_CLEANUP_SECONDS,
        budget.finalization_policy.finalization_time_reserve_seconds_per_attempt
        / 2,
    )
    deadline = budget.tool_execution_deadline(cleanup_seconds=cleanup_seconds)
    lease_seconds = max(0.0, deadline - budget.monotonic())
    control = RuntimeToolExecutionControl(
        deadline_monotonic=deadline,
        deadline_utc=datetime.now(tz=UTC) + timedelta(seconds=lease_seconds),
        execution_lease_id=str(uuid4()),
        cancellation=Event(),
        monotonic=budget.monotonic,
        external_cancellation=cancellation,
    )
    cancellation_callback_id = cancellation.add_callback(
        lambda: control.cancel("runtime_cancelled")
    )
    try:
        if (
            outcome.invocation.resolved_tool_handle
            in _CANCELLATION_QUIESCENT_TOOL_HANDLES
        ):
            # Close the spawn-before-callback race: cancellation must await these
            # cooperative surfaces even if their worker has not registered cleanup.
            control.require_quiescence()
        started = tool_orchestrator.start_authorized(
            outcome.invocation,
            authority=authority,
            context=context,
            control=control,
        )
        if started.invocation.state != "executing":
            return started
        task = asyncio.create_task(
            asyncio.to_thread(
                tool_orchestrator.execute_started,
                started.invocation,
                authority=authority,
                context=context,
                policy=policy,
                control=control,
            )
        )
        failure_reason: str | None = None
        while not task.done():
            if cancellation.is_set():
                failure_reason = "runtime_cancelled"
                break
            remaining = deadline - budget.monotonic()
            if remaining <= 0:
                failure_reason = "agent_finalization_time_reserve_reached"
                break
            await asyncio.wait((task,), timeout=min(poll_seconds, remaining))
        if failure_reason is None and cancellation.is_set():
            failure_reason = "runtime_cancelled"
        if failure_reason is None:
            return await task
        # The external signal shares the COW commit gate, while the lease event
        # fences the ledger and synchronously runs registered surface cleanup.
        await asyncio.to_thread(control.cancel, failure_reason)
        interrupted = tool_orchestrator.interrupt_started_execution(
            started.invocation,
            failure_reason=failure_reason,
        )
        if control.requires_quiescence:
            try:
                await task
            except Exception:
                # Cancellation owns the public outcome; the ledger fence above is
                # already authoritative, but worker quiescence remains mandatory.
                pass
        else:
            task.add_done_callback(_consume_background_result)
        if failure_reason == "runtime_cancelled":
            raise HostedAgenticLoopError(failure_reason)
        return interrupted
    finally:
        cancellation.remove_callback(cancellation_callback_id)


def _consume_background_result(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    try:
        task.result()
    except Exception:
        pass
