"""Shared sequential orchestration loop for hosted agentic model providers."""

from __future__ import annotations

from collections.abc import AsyncIterator
import asyncio
from dataclasses import replace
import json
from threading import Event
from typing import Callable

from core.providers.agentic_protocol import AgenticToolResult
from core.providers.agentic_adapter import RuntimeProviderEvent, RuntimeTurnContext
from core.runtime.hosted_agentic_budget import HostedAgenticBudget
from core.runtime.hosted_agentic_models import (
    HostedActorContextResolver,
    HostedAgenticLoopError,
    HostedAuthorityRefresher,
    HostedCredentialResolver,
    HostedPolicyResolver,
    HostedToolOrchestratorResolver,
    HostedTurnStatusCallback,
    raise_if_hosted_cancelled,
)
from core.runtime.hosted_agentic_request import HostedAgenticRequestBuilder
from core.runtime.hosted_agentic_policy import (
    destination_upstream,
    hosted_egress_policy,
    hosted_tool_policy,
    normalized_tool_result,
    tool_event_payload,
)
from core.runtime.hosted_agentic_state import HostedAgenticStateBridge
from core.runtime.hosted_agentic_stream import (
    HostedProviderStep,
    consume_hosted_provider_step,
)
from core.runtime.hosted_agentic_tool_results import make_agentic_tool_result
from core.runtime.provider_private_state import ProviderPrivateStateService
from core.runtime.hosted_provider_runtime import HostedProviderRuntimeRegistry
from core.runtime.tool_errors import RuntimeToolError
from core.runtime.tool_orchestrator import RuntimeToolInvocationOutcome
from core.runtime.tool_ledger import RuntimeToolLedger


class HostedAgenticLoop:
    """Own budgets, egress, tools, confirmation and provider-private state."""

    def __init__(
        self,
        *,
        provider_runtimes: HostedProviderRuntimeRegistry,
        request_builder: HostedAgenticRequestBuilder,
        tool_orchestrator_resolver: HostedToolOrchestratorResolver,
        tool_ledger: RuntimeToolLedger,
        private_state_service: ProviderPrivateStateService,
        policy_resolver: HostedPolicyResolver,
        authority_refresher: HostedAuthorityRefresher,
        actor_context_resolver: HostedActorContextResolver,
        credential_resolver: HostedCredentialResolver,
        turn_status_callback: HostedTurnStatusCallback | None = None,
        confirmation_poll_seconds: float = 0.05,
    ) -> None:
        self.provider_runtimes = provider_runtimes
        self.request_builder = request_builder
        self.tool_orchestrator_resolver = tool_orchestrator_resolver
        self.tool_ledger = tool_ledger
        self.private_state_service = private_state_service
        self.policy_resolver = policy_resolver
        self.authority_refresher = authority_refresher
        self.actor_context_resolver = actor_context_resolver
        self.credential_resolver = credential_resolver
        self.turn_status_callback = turn_status_callback
        self.confirmation_poll_seconds = max(0.01, confirmation_poll_seconds)

    @property
    def artifact_components(self) -> tuple[object, ...]:
        """Expose shared orchestration modules to the adapter artifact digest."""
        return (
            HostedAgenticBudget,
            HostedAgenticRequestBuilder,
            HostedAgenticStateBridge,
            HostedProviderStep,
        )

    async def execute(
        self,
        context: RuntimeTurnContext,
        *,
        cancellation: Event,
    ) -> AsyncIterator[RuntimeProviderEvent]:
        ordinal = 0

        def event(event_type: str, payload: dict[str, object]) -> RuntimeProviderEvent:
            nonlocal ordinal
            ordinal += 1
            return RuntimeProviderEvent(event_type, context.correlation_id, ordinal, "1", payload)

        failure_reason: str | None = None
        try:
            async for item in self._execute(context, cancellation=cancellation, event=event):
                yield item
        except HostedAgenticLoopError as error:
            failure_reason = error.reason_code
        except RuntimeToolError as error:
            failure_reason = error.reason_code
        except Exception:
            failure_reason = "hosted_runtime_failed"
        if failure_reason is not None:
            yield event("runtime.error", {"reason_code": failure_reason})
            yield event(
                "provider.execution.completed",
                {"output_text": "", "exit_code": 1, "reason_code": failure_reason},
            )

    async def _execute(
        self,
        context: RuntimeTurnContext,
        *,
        cancellation: Event,
        event: Callable[[str, dict[str, object]], RuntimeProviderEvent],
    ) -> AsyncIterator[RuntimeProviderEvent]:
        authority = self.authority_refresher(context)
        policy = self.policy_resolver(context)
        provider_runtime = self.provider_runtimes.resolve(context.binding)
        private_state = HostedAgenticStateBridge(
            service=self.private_state_service,
            codec=provider_runtime.private_codec,
        )
        budget = HostedAgenticBudget(policy)
        egress_policy = hosted_egress_policy(context, policy)
        destination_upstream_id = destination_upstream(context)
        tool_results: list[AgenticToolResult] = []
        private_state.fence_turn(context)
        for step in range(policy.max_steps_per_turn + 1):
            raise_if_hosted_cancelled(cancellation)
            policy = self.policy_resolver(context)
            budget.tighten(policy)
            egress_policy = hosted_egress_policy(context, budget.policy)
            authority = self.authority_refresher(context)
            actor_context = self.actor_context_resolver(
                replace(context, effective_authority=authority)
            )
            provider_private_state = private_state.read(context, authority)
            tool_orchestrator = self.tool_orchestrator_resolver(context, actor_context)
            catalog = tool_orchestrator.materialize(
                authority=authority,
                context=actor_context,
            )
            request = self.request_builder.build(
                context=context,
                step=step,
                input_text=context.input_text,
                catalog=catalog,
                tool_results=tuple(tool_results),
                provider_private_state=provider_private_state,
                egress_policy=egress_policy,
                destination_upstream_id=destination_upstream_id,
                max_output_tokens=max(1, budget.policy.max_output_tokens - budget.output_tokens),
            )
            budget.begin_step(request, provider_runtime.cost_estimator(request))
            private_state.persist_request_identity(context, request.request_id)
            yield event(
                "provider.request.sent",
                {"request_id": request.request_id, "step": step + 1},
            )
            response: HostedProviderStep | None = None
            async for emission in consume_hosted_provider_step(
                client=provider_runtime.client,
                request=request,
                credential=self.credential_resolver(context),
                budget=budget,
                cancellation=cancellation,
                destination_upstream_id=destination_upstream_id,
                on_private_state=lambda provider_event: private_state.store(
                    context,
                    self.authority_refresher(context),
                    provider_event,
                ),
            ):
                if emission.event_type is not None and emission.payload is not None:
                    yield event(emission.event_type, emission.payload)
                if emission.response is not None:
                    response = emission.response
            if response is None:
                raise HostedAgenticLoopError("provider_response_invalid")
            if response.final_text is not None:
                yield event("runtime.output.final", {"text": response.final_text})
                yield event(
                    "provider.execution.completed",
                    {"output_text": response.final_text, "exit_code": 0},
                )
                return
            if response.tool_call is None:
                raise HostedAgenticLoopError("provider_response_invalid")
            budget.add_tool_call()
            authority = self.authority_refresher(context)
            actor_context = self.actor_context_resolver(
                replace(context, effective_authority=authority)
            )
            tool_orchestrator = self.tool_orchestrator_resolver(context, actor_context)
            budget.tighten(self.policy_resolver(context))
            tool_policy = hosted_tool_policy(authority, budget.policy)
            outcome = tool_orchestrator.invoke_provider_tool(
                provider_tool_name=response.tool_call.provider_tool_name,
                provider_tool_call_id=response.tool_call.provider_tool_call_id,
                arguments=response.tool_call.arguments,
                authority=authority,
                context=actor_context,
                turn_id=context.correlation_id,
                policy=tool_policy,
            )
            yield event(
                "runtime.tool_call.proposed",
                tool_event_payload(outcome, display_state="proposed"),
            )
            if outcome.awaiting_confirmation:
                yield event("runtime.tool_call.awaiting_confirmation", tool_event_payload(outcome))
                outcome = await self._await_confirmation(
                    context=context,
                    cancellation=cancellation,
                    budget=budget,
                    outcome=outcome,
                )
            if outcome.invocation.state == "execution_unknown":
                yield event("runtime.tool_call.execution_unknown", tool_event_payload(outcome))
                raise HostedAgenticLoopError("tool_execution_unknown")
            if outcome.invocation.state == "succeeded":
                yield event(
                    "runtime.tool_call.started",
                    tool_event_payload(outcome, display_state="executing"),
                )
            result, is_error = normalized_tool_result(tool_orchestrator, outcome)
            tool_event_type = (
                "runtime.tool_call.completed"
                if outcome.invocation.state == "succeeded"
                else "runtime.tool_call.failed"
            )
            yield event(tool_event_type, tool_event_payload(outcome))
            serialized_size = len(
                json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
            )
            budget.add_tool_result(serialized_size)
            budget.tighten(self.policy_resolver(context))
            egress_policy = hosted_egress_policy(context, budget.policy)
            tool_results.append(
                make_agentic_tool_result(
                    provider_tool_call_id=response.tool_call.provider_tool_call_id,
                    provider_tool_name=response.tool_call.provider_tool_name,
                    result=result,
                    is_error=is_error,
                )
            )
        raise HostedAgenticLoopError("agent_step_limit_reached")

    async def _await_confirmation(
        self,
        *,
        context,
        cancellation: Event,
        budget: HostedAgenticBudget,
        outcome: RuntimeToolInvocationOutcome,
    ) -> RuntimeToolInvocationOutcome:
        invocation_id = outcome.invocation.invocation_id
        if self.turn_status_callback is not None:
            self.turn_status_callback("waiting_for_tool_confirmation", invocation_id)
        try:
            while True:
                raise_if_hosted_cancelled(cancellation)
                budget.check_time()
                record = self.tool_ledger.store.get_tool_invocation(invocation_id)
                if record.state != "awaiting_confirmation":
                    self._resume_turn(invocation_id)
                    return RuntimeToolInvocationOutcome(record)
                if record.confirmation_grant_id:
                    authority = self.authority_refresher(context)
                    budget.tighten(self.policy_resolver(context))
                    actor_context = self.actor_context_resolver(
                        replace(context, effective_authority=authority)
                    )
                    orchestrator = self.tool_orchestrator_resolver(context, actor_context)
                    resumed = orchestrator.resume_confirmed(
                        invocation_id=invocation_id,
                        grant_id=record.confirmation_grant_id,
                        authority=authority,
                        context=actor_context,
                        policy=hosted_tool_policy(authority, budget.policy),
                    )
                    self._resume_turn(invocation_id)
                    return resumed
                await asyncio.sleep(self.confirmation_poll_seconds)
        except HostedAgenticLoopError as error:
            record = self.tool_ledger.store.get_tool_invocation(invocation_id)
            if record.state == "awaiting_confirmation":
                target = "cancelled" if error.reason_code == "runtime_cancelled" else "expired"
                self.tool_ledger.transition(
                    record,
                    target,
                    failure_reason=error.reason_code,
                )
            self._resume_turn(invocation_id)
            raise

    def _resume_turn(self, invocation_id: str) -> None:
        if self.turn_status_callback is not None:
            self.turn_status_callback("active", invocation_id)
