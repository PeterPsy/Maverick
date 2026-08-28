"""Shared sequential orchestration loop for hosted agentic model providers."""

from __future__ import annotations

from collections.abc import AsyncIterator
import asyncio
from dataclasses import replace
from datetime import UTC, datetime
import json
from threading import Event
from typing import Callable
from uuid import NAMESPACE_URL, uuid5

import core.egress.agentic_models as agentic_egress_models_module
import core.egress.agentic_policy as agentic_egress_policy_module
import core.egress.agentic_transforms as agentic_egress_transforms_module
import core.providers.agentic_reason_codes as agentic_reason_codes_module
import core.runtime.hosted_agentic_budget as hosted_agentic_budget_module
import core.runtime.hosted_agentic_budget_models as hosted_agentic_budget_models_module
import core.runtime.hosted_agentic_budget_recovery as hosted_agentic_budget_recovery_module
import core.runtime.hosted_agentic_finalization_budget as hosted_agentic_finalization_budget_module
import core.runtime.hosted_agentic_policy as hosted_agentic_policy_module
import core.runtime.hosted_agentic_request as hosted_agentic_request_module
import core.runtime.hosted_agentic_recovery as hosted_agentic_recovery_module
import core.runtime.hosted_agentic_state as hosted_agentic_state_module
import core.runtime.hosted_agentic_stream as hosted_agentic_stream_module
import core.runtime.hosted_agentic_tool_execution as hosted_agentic_tool_execution_module
import core.runtime.provider_step_journal as provider_step_journal_module
import core.runtime.hosted_agentic_tool_results as hosted_agentic_tool_results_module
import core.runtime.hosted_provider_runtime as hosted_provider_runtime_module
import core.runtime.tool_core_capabilities as tool_core_capabilities_module
import core.runtime.tool_filesystem_listing as tool_filesystem_listing_module
import core.runtime.tool_orchestrator as tool_orchestrator_module
from core.providers.agentic_protocol import (
    AgenticModelEvent,
    AgenticModelRequest,
    AgenticToolResult,
)
from core.providers.agentic_adapter import RuntimeProviderEvent, RuntimeTurnContext
from core.runtime.hosted_agentic_budget import HostedAgenticBudget
from core.runtime.agentic_feature_flags import (
    MAVERICK_FEATURE_AGENTIC_ADAPTER_CONTRACT,
    MAVERICK_FEATURE_AGENTIC_PROFILES,
    MAVERICK_FEATURE_AGENTIC_TOOL_CONFIRMATION,
    MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME,
    MAVERICK_FEATURE_PROVIDER_PRIVATE_STATE,
    feature_enabled,
    require_agentic_feature,
)
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
from core.runtime.hosted_agentic_request import (
    HostedAgenticRequestBuilder,
    hosted_request_control_digest,
    hosted_request_lineage_digest,
)
from core.runtime.hosted_agentic_recovery import HostedAgenticRecovery
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
from core.runtime.hosted_agentic_tool_execution import (
    execute_hosted_authorized_tool,
)
from core.runtime.confined_filesystem import ConfinedWorkspaceFilesystem
from core.runtime.provider_private_state import ProviderPrivateStateService
from core.runtime.provider_step_journal import ProviderStepJournal
from core.runtime.provider_step_models import ProviderStepJournalRecord
from core.runtime.hosted_provider_runtime import HostedProviderRuntimeRegistry
from core.runtime.tool_errors import RuntimeToolError
from core.runtime.tool_core_capabilities import build_core_runtime_tool_capabilities
from core.runtime.tool_catalog import RuntimeToolCatalog
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
        provider_step_journal: ProviderStepJournal | None = None,
        recovery: HostedAgenticRecovery | None = None,
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
        self.provider_step_journal = provider_step_journal or ProviderStepJournal(
            store=tool_ledger.store
        )
        self.recovery = recovery or HostedAgenticRecovery(
            journal=self.provider_step_journal,
            tool_ledger=tool_ledger,
            private_state_service=private_state_service,
        )

    @property
    def artifact_components(self) -> tuple[object, ...]:
        """Expose shared orchestration modules to the adapter artifact digest."""
        return (
            agentic_egress_models_module,
            agentic_egress_policy_module,
            agentic_egress_transforms_module,
            agentic_reason_codes_module,
            hosted_agentic_budget_module,
            hosted_agentic_budget_models_module,
            hosted_agentic_budget_recovery_module,
            hosted_agentic_finalization_budget_module,
            hosted_agentic_policy_module,
            hosted_agentic_request_module,
            hosted_agentic_recovery_module,
            hosted_agentic_state_module,
            hosted_agentic_stream_module,
            hosted_agentic_tool_execution_module,
            hosted_agentic_tool_results_module,
            hosted_provider_runtime_module,
            tool_core_capabilities_module,
            tool_filesystem_listing_module,
            tool_orchestrator_module,
            provider_step_journal_module,
            build_core_runtime_tool_capabilities,
            ConfinedWorkspaceFilesystem.list_entries,
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
            recovered_reason = self._recover_after_failure(
                context,
                trigger=(
                    f"cancellation_uncertain:{failure_reason}"
                    if failure_reason == "runtime_cancelled"
                    else f"execution_failure:{failure_reason}"
                ),
            )
            if recovered_reason is not None:
                failure_reason = recovered_reason
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
        require_agentic_feature(
            MAVERICK_FEATURE_AGENTIC_PROFILES,
            "agentic_profiles_disabled",
        )
        require_agentic_feature(
            MAVERICK_FEATURE_AGENTIC_ADAPTER_CONTRACT,
            "agentic_adapter_contract_disabled",
        )
        require_agentic_feature(
            MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME,
            "hosted_agent_runtime_disabled",
        )
        require_agentic_feature(
            MAVERICK_FEATURE_PROVIDER_PRIVATE_STATE,
            "provider_private_state_disabled",
        )
        authority = self.authority_refresher(context)
        policy = self.policy_resolver(context)
        provider_runtime = self.provider_runtimes.resolve(context.binding)
        private_state = HostedAgenticStateBridge(
            service=self.private_state_service,
            codec=provider_runtime.private_codec,
        )
        egress_policy = hosted_egress_policy(context, policy)
        destination_upstream_id = destination_upstream(context)
        tool_results: list[AgenticToolResult] = []
        existing_turn_steps = self.tool_ledger.store.list_provider_step_journals(
            session_id=context.session.session_id,
            turn_id=context.correlation_id,
        )
        committed_final = next(
            (
                item
                for item in reversed(existing_turn_steps)
                if item.commit_status == "committed"
                and item.final_output_validated
            ),
            None,
        )
        if committed_final is not None:
            output_text = self._read_final_output(
                context,
                provider_runtime,
                committed_final,
            )
            if committed_final.final_output_status == "ready":
                yield event(
                    "runtime.output.final",
                    {
                        "text": output_text,
                        "complete_text": output_text,
                        "provider_id": context.binding.model_provider_id,
                        "exit_code": 0,
                        "delivery_id": committed_final.final_output_id,
                    },
                )
                committed_final = self.provider_step_journal.mark_final_output_delivered(
                    self.tool_ledger.store.get_provider_step_journal(
                        committed_final.journal_id
                    )
                )
            elif committed_final.final_output_status != "delivered":
                raise HostedAgenticLoopError("provider_state_ambiguous")
            if committed_final.final_completion_status == "ready":
                yield event(
                    "provider.execution.completed",
                    {
                        "output_text": output_text,
                        "exit_code": 0,
                        "delivery_id": committed_final.final_output_id,
                    },
                )
                self.provider_step_journal.mark_final_completion_delivered(
                    self.tool_ledger.store.get_provider_step_journal(
                        committed_final.journal_id
                    )
                )
            elif committed_final.final_completion_status != "delivered":
                raise HostedAgenticLoopError("provider_state_ambiguous")
            return
        budget = HostedAgenticBudget(
            policy,
            provider_runtime.finalization_policy,
            elapsed_seconds=_turn_budget_elapsed(existing_turn_steps),
        )
        budget.restore(existing_turn_steps)
        start_step = (
            max(item.step_index for item in existing_turn_steps) + 1
            if existing_turn_steps
            else 0
        )
        pairing_source = self.recovery.pending_pairing(
            session_id=context.session.session_id,
            turn_id=context.correlation_id,
        )
        if pairing_source is not None:
            for invocation in self.recovery.pairing_results(pairing_source):
                result, is_error = normalized_tool_result(
                    self.tool_orchestrator_resolver(
                        context,
                        self.actor_context_resolver(context),
                    ),
                    RuntimeToolInvocationOutcome(invocation),
                )
                tool_results.append(
                    make_agentic_tool_result(
                        provider_tool_call_id=invocation.provider_tool_call_id,
                        provider_tool_name=invocation.provider_safe_name,
                        result=result,
                        is_error=is_error,
                        invocation=invocation,
                    )
                )
        private_state.fence_turn(context)
        step = start_step
        while True:
            raise_if_hosted_cancelled(cancellation)
            policy = self.policy_resolver(context)
            budget.tighten(policy)
            egress_policy = hosted_egress_policy(context, budget.policy)
            authority = self.authority_refresher(context)
            effective_context = replace(context, effective_authority=authority)
            credential = self.credential_resolver(context)
            if provider_runtime.credential_required and credential is None:
                raise HostedAgenticLoopError(
                    "provider_credential_authorization_missing"
                )
            actor_context = self.actor_context_resolver(effective_context)
            provider_private_state = private_state.read(context, authority)
            tool_orchestrator = self.tool_orchestrator_resolver(context, actor_context)
            phase = budget.select_phase(
                pairing_source=pairing_source,
                existing_records=existing_turn_steps,
            )
            while True:
                step_plan = budget.plan_step(phase)
                catalog = (
                    tool_orchestrator.materialize(
                        authority=authority,
                        context=actor_context,
                    )
                    if phase == "exploration"
                    else RuntimeToolCatalog(())
                )
                prepared_request = self.request_builder.prepare(
                    context=effective_context,
                    step=step,
                    input_text=context.input_text,
                    catalog=catalog,
                    tool_results=tuple(tool_results),
                    provider_private_state=provider_private_state,
                    egress_policy=egress_policy,
                    destination_upstream_id=destination_upstream_id,
                    max_output_tokens=step_plan.max_output_tokens,
                    request_phase=phase,
                    pairing_source=pairing_source,
                )
                request = prepared_request.request
                request_lineage_digest = hosted_request_lineage_digest(request)
                request_control_digest = hosted_request_control_digest(request)
                self._validate_request_pairing(
                    request,
                    pairing_source=pairing_source,
                    turn_id=context.correlation_id,
                    request_lineage_digest=request_lineage_digest,
                )
                try:
                    reservation = budget.begin_step(
                        request,
                        provider_runtime.cost_estimator(request),
                        phase=phase,
                    )
                except HostedAgenticLoopError as error:
                    if (
                        phase == "exploration"
                        and error.reason_code
                        == "agent_finalization_reserve_unavailable"
                    ):
                        phase = "finalization"
                        continue
                    raise
                request = self.request_builder.commit(prepared_request)
                break
            private_state.persist_request_identity(context, request)
            provider_state_snapshot = self.tool_ledger.store.get_provider_state(
                context.session.session_id
            )
            step_journal = self.provider_step_journal.begin_request(
                session=context.session,
                binding=context.binding,
                provider_state=provider_state_snapshot,
                request_id=request.request_id,
                turn_id=context.correlation_id,
                step_index=step,
                codec=provider_runtime.private_codec,
                pairing_source_journal_id=(
                    None if pairing_source is None else pairing_source.journal_id
                ),
                request_lineage_digest=request_lineage_digest,
                request_control_digest=request_control_digest,
                request_phase=phase,
                request_max_output_tokens=request.max_output_tokens,
                budget_estimated_input_tokens=reservation.estimated_input_tokens,
                budget_estimated_cost_microusd=(
                    reservation.estimated_cost_microusd
                ),
            )
            step_journal = self.provider_step_journal.journal_request(step_journal)
            yield event(
                "provider.request.sent",
                {
                    "request_id": request.request_id,
                    "step": step + 1,
                    "phase": phase,
                    "budget": reservation.snapshot.public_payload(),
                },
            )
            response: HostedProviderStep | None = None
            observed: dict[str, RuntimeToolInvocationOutcome] = {}
            staged_envelope = None

            def accepted(provider_event: AgenticModelEvent) -> None:
                nonlocal step_journal
                step_journal = self.provider_step_journal.accept(
                    step_journal,
                    provider_response_id=provider_event.provider_response_id,
                    provider_upstream_id=provider_event.upstream_id,
                )

            def observe(provider_event: AgenticModelEvent) -> dict[str, object]:
                nonlocal step_journal
                call = provider_event.tool_call
                if call is None:
                    raise HostedAgenticLoopError("provider_response_invalid")
                outcome = tool_orchestrator.observe_provider_tool(
                    provider_tool_name=call.provider_tool_name,
                    provider_tool_call_id=call.provider_tool_call_id,
                    arguments=call.ledger_arguments,
                    provider_request_id=request.request_id,
                    provider_event_ordinal=provider_event.ordinal,
                    provider_call_index=call.call_index,
                    authority=authority,
                    context=actor_context,
                    turn_id=context.correlation_id,
                    policy=hosted_tool_policy(authority, budget.policy),
                )
                existing = observed.get(call.provider_tool_call_id)
                if existing is not None and (
                    existing.invocation.arguments_digest
                    != outcome.invocation.arguments_digest
                ):
                    raise HostedAgenticLoopError("tool_provider_call_replay_mismatch")
                observed[call.provider_tool_call_id] = outcome
                charge_tool_budget = False
                budget_error: HostedAgenticLoopError | None = None
                if phase == "exploration":
                    try:
                        budget.check_tool_call()
                    except HostedAgenticLoopError as error:
                        budget_error = error
                    else:
                        charge_tool_budget = True
                previous_observed = step_journal.observed_call_count
                previous_charges = step_journal.budget_tool_call_charges
                step_journal = self.provider_step_journal.add_proposal(
                    step_journal,
                    outcome.invocation.proposal_id,
                    charge_tool_budget=charge_tool_budget,
                )
                proposal_added = step_journal.observed_call_count > previous_observed
                if (
                    proposal_added
                    and step_journal.budget_tool_call_charges > previous_charges
                ):
                    budget.add_tool_call()
                if (
                    budget_error is not None
                    and budget_error.reason_code != "agent_tool_call_limit_reached"
                ):
                    raise budget_error
                return tool_event_payload(outcome, display_state="proposed")

            def stage(provider_event: AgenticModelEvent) -> None:
                nonlocal step_journal, staged_envelope
                if staged_envelope is not None:
                    raise HostedAgenticLoopError("provider_private_state_invalid")
                staged_envelope = private_state.store(
                    context,
                    authority,
                    provider_event,
                )
                step_journal = self.provider_step_journal.stage_provider_state(
                    step_journal,
                    staged_envelope,
                )

            def record_usage(provider_event: AgenticModelEvent) -> None:
                nonlocal step_journal
                usage = provider_event.usage
                if usage is None:
                    raise HostedAgenticLoopError("provider_response_invalid")
                step_journal = self.provider_step_journal.record_usage(
                    step_journal,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cost_microusd=usage.estimated_cost_microusd,
                )

            try:
                async for emission in consume_hosted_provider_step(
                    client=provider_runtime.client,
                    request=request,
                    credential=credential,
                    budget=budget,
                    cancellation=cancellation,
                    destination_upstream_id=destination_upstream_id,
                    on_accepted=accepted,
                    on_tool_call=observe,
                    on_private_state=stage,
                    on_usage=record_usage,
                ):
                    if emission.event_type is not None and emission.payload is not None:
                        yield event(emission.event_type, emission.payload)
                    if emission.response is not None:
                        response = emission.response
            except Exception as error:
                current_journal = self.tool_ledger.store.get_provider_step_journal(
                    step_journal.journal_id
                )
                if current_journal.stream_status == "pending":
                    current_journal = self.provider_step_journal.fail_stream(
                        current_journal,
                        reason_code=(
                            error.reason_code
                            if isinstance(error, HostedAgenticLoopError)
                            else "provider_response_invalid"
                        ),
                    )
                if self.provider_step_journal.is_proven_terminal_failure(
                    current_journal
                ):
                    self.provider_step_journal.roll_back_proven_terminal_failure(
                        current_journal
                    )
                raise
            if response is None:
                raise HostedAgenticLoopError("provider_response_invalid")
            step_journal = self.tool_ledger.store.get_provider_step_journal(
                step_journal.journal_id
            )
            if staged_envelope is None:
                raise HostedAgenticLoopError("provider_private_state_invalid")
            if response.final_text is not None:
                if not response.final_text.strip():
                    step_journal = (
                        self.provider_step_journal.reject_invalid_final_output(
                            step_journal,
                            reason_code="agent_final_output_empty",
                        )
                    )
                    self.provider_step_journal.roll_back_proven_terminal_failure(
                        step_journal
                    )
                    raise HostedAgenticLoopError("agent_final_output_empty")
                output_id = str(
                    uuid5(
                        NAMESPACE_URL,
                        f"maverick:provider-final-output:{step_journal.journal_id}",
                    )
                )
                private_ref, content_sha256, size_bytes = (
                    self.private_state_service.store_final_output(
                        session_id=context.session.session_id,
                        adapter_id=context.binding.adapter_id,
                        adapter_version=context.binding.adapter_version,
                        codec_id=provider_runtime.private_codec.codec_id,
                        codec_version=provider_runtime.private_codec.codec_version,
                        schema_version=provider_runtime.private_codec.schema_version,
                        journal_id=step_journal.journal_id,
                        provider_request_id=step_journal.request_id,
                        output_text=response.final_text,
                    )
                )
                step_journal = self.provider_step_journal.stage_final_output(
                    step_journal,
                    output_id=output_id,
                    private_ref=private_ref,
                    content_sha256=content_sha256,
                    size_bytes=size_bytes,
                )
                step_journal = self.provider_step_journal.complete_stream(
                    step_journal,
                    final_output_validated=True,
                )
                private_state.promote(
                    context,
                    staged_envelope,
                    expected_revision=step_journal.base_provider_state_revision,
                )
                step_journal = self.provider_step_journal.mark_committed(step_journal)
                if pairing_source is not None:
                    pairing_source = self.provider_step_journal.mark_pairing_consumed(
                        self.tool_ledger.store.get_provider_step_journal(
                            pairing_source.journal_id
                        )
                    )
                yield event(
                    "runtime.output.final",
                    {
                        "text": response.final_text,
                        "complete_text": response.final_text,
                        "provider_id": context.binding.model_provider_id,
                        "exit_code": 0,
                        "delivery_id": output_id,
                    },
                )
                step_journal = self.provider_step_journal.mark_final_output_delivered(
                    self.tool_ledger.store.get_provider_step_journal(
                        step_journal.journal_id
                    )
                )
                yield event(
                    "provider.execution.completed",
                    {
                        "output_text": response.final_text,
                        "exit_code": 0,
                        "delivery_id": output_id,
                    },
                )
                self.provider_step_journal.mark_final_completion_delivered(
                    self.tool_ledger.store.get_provider_step_journal(
                        step_journal.journal_id
                    )
                )
                budget.complete_step()
                return
            step_journal = self.provider_step_journal.complete_stream(
                step_journal,
                final_output_validated=False,
            )
            if not response.tool_calls:
                raise HostedAgenticLoopError("provider_response_invalid")
            step_results: list[AgenticToolResult] = []
            parallel_denied = len(response.tool_calls) > 1
            post_pairing_failure: str | None = None
            tool_policy = hosted_tool_policy(authority, budget.policy)
            for call_index, call in enumerate(response.tool_calls):
                outcome = observed.get(call.provider_tool_call_id)
                if outcome is None:
                    raise HostedAgenticLoopError("provider_pairing_ambiguous")
                if phase != "exploration":
                    outcome = tool_orchestrator.deny_observed_tool(
                        outcome.invocation,
                        resolution_status="budget_denied",
                        failure_reason="agent_finalization_tool_call_forbidden",
                    )
                elif call_index >= step_journal.budget_tool_call_charges:
                    outcome = tool_orchestrator.deny_observed_tool(
                        outcome.invocation,
                        resolution_status="budget_denied",
                        failure_reason="agent_tool_call_limit_reached",
                    )
                elif parallel_denied:
                    outcome = tool_orchestrator.deny_observed_tool(
                        outcome.invocation,
                        resolution_status="parallel_denied",
                        failure_reason="provider_parallel_tool_calls_forbidden",
                    )
                else:
                    try:
                        authority = self.authority_refresher(context)
                        budget.tighten(self.policy_resolver(context))
                        budget.require_finalization_reserve()
                        actor_context = self.actor_context_resolver(
                            replace(context, effective_authority=authority)
                        )
                        tool_orchestrator = self.tool_orchestrator_resolver(
                            context,
                            actor_context,
                        )
                        tool_policy = hosted_tool_policy(authority, budget.policy)
                    except HostedAgenticLoopError as error:
                        outcome = tool_orchestrator.deny_observed_tool(
                            outcome.invocation,
                            resolution_status=(
                                "budget_denied"
                                if error.reason_code.startswith("agent_")
                                else "revoked"
                            ),
                            failure_reason=error.reason_code,
                        )
                        post_pairing_failure = error.reason_code
                    else:
                        outcome = tool_orchestrator.prepare_observed_tool(
                            outcome.invocation,
                            requested_catalog=catalog,
                            authority=authority,
                            context=actor_context,
                            policy=tool_policy,
                        )
                if outcome.awaiting_confirmation:
                    if not feature_enabled(MAVERICK_FEATURE_AGENTIC_TOOL_CONFIRMATION):
                        outcome = RuntimeToolInvocationOutcome(
                            self.tool_ledger.cancel_before_effect(
                                outcome.invocation,
                                reason_code="agentic_tool_confirmation_disabled",
                            )
                        )
                    else:
                        yield event(
                            "runtime.tool_call.awaiting_confirmation",
                            tool_event_payload(outcome),
                        )
                        outcome = await self._await_confirmation(
                            context=context,
                            cancellation=cancellation,
                            budget=budget,
                            outcome=outcome,
                        )
                if outcome.invocation.state in {
                    "denied",
                    "failed",
                    "cancelled",
                    "expired",
                    "execution_unknown",
                } and outcome.invocation.result_id is None:
                    outcome = RuntimeToolInvocationOutcome(
                        self.tool_ledger.attach_terminal_result(outcome.invocation)
                    )
                if outcome.invocation.disposition_id is not None:
                    step_journal = self.provider_step_journal.add_disposition(
                        step_journal,
                        outcome.invocation.disposition_id,
                    )
                if outcome.invocation.state == "authorized":
                    yield event(
                        "runtime.tool_call.started",
                        tool_event_payload(outcome, display_state="executing"),
                    )
                    outcome = await execute_hosted_authorized_tool(
                        tool_orchestrator=tool_orchestrator,
                        outcome=outcome,
                        authority=authority,
                        context=actor_context,
                        policy=tool_policy,
                        budget=budget,
                        cancellation=cancellation,
                        poll_seconds=self.confirmation_poll_seconds,
                    )
                if outcome.invocation.result_id is None:
                    raise HostedAgenticLoopError("tool_result_unavailable")
                step_journal = self.provider_step_journal.add_result(
                    step_journal,
                    outcome.invocation.result_id,
                )
                if outcome.invocation.state == "execution_unknown":
                    yield event(
                        "runtime.tool_call.execution_unknown",
                        tool_event_payload(outcome),
                    )
                    raise HostedAgenticLoopError("tool_execution_unknown")
                result, is_error = normalized_tool_result(tool_orchestrator, outcome)
                tool_event_type = (
                    "runtime.tool_call.completed"
                    if outcome.invocation.state == "succeeded"
                    else "runtime.tool_call.failed"
                )
                yield event(tool_event_type, tool_event_payload(outcome))
                serialized_size = len(
                    json.dumps(
                        result,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ).encode()
                )
                step_journal = self.provider_step_journal.record_tool_result_bytes(
                    step_journal,
                    total_bytes=(
                        step_journal.budget_tool_result_bytes + serialized_size
                    ),
                )
                budget.add_tool_result(serialized_size)
                budget.tighten(self.policy_resolver(context))
                egress_policy = hosted_egress_policy(context, budget.policy)
                step_results.append(
                    make_agentic_tool_result(
                        provider_tool_call_id=call.provider_tool_call_id,
                        provider_tool_name=call.provider_tool_name,
                        result=result,
                        is_error=is_error,
                        invocation=outcome.invocation,
                    )
                )
            step_journal = self.provider_step_journal.complete_dispositions(step_journal)
            step_journal = self.provider_step_journal.mark_pairing_ready(step_journal)
            private_state.promote(
                context,
                staged_envelope,
                expected_revision=step_journal.base_provider_state_revision,
            )
            step_journal = self.provider_step_journal.mark_committed(step_journal)
            if pairing_source is not None:
                self.provider_step_journal.mark_pairing_consumed(
                    self.tool_ledger.store.get_provider_step_journal(
                        pairing_source.journal_id
                    )
                )
            pairing_source = step_journal
            tool_results = step_results
            existing_turn_steps.append(step_journal)
            budget.complete_step()
            if post_pairing_failure is not None:
                raise HostedAgenticLoopError(post_pairing_failure)
            if phase == "finalization_recovery":
                raise HostedAgenticLoopError(
                    "agent_finalization_recovery_exhausted"
                )
            step += 1

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
                    resumed = orchestrator.authorize_confirmed(
                        invocation_id=invocation_id,
                        grant_id=record.confirmation_grant_id,
                        authority=authority,
                        context=actor_context,
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

    def recover_session(self, context, *, trigger: str):
        """Synchronous lifecycle hook used by startup, admission and prepare."""
        runtime = self.provider_runtimes.resolve(context.binding)
        return self.recovery.recover(
            session=context.session,
            binding=context.binding,
            provider_runtime=runtime,
            trigger=trigger,
        )

    def _recover_after_failure(self, context, *, trigger: str) -> str | None:
        failure_reason = trigger.partition(":")[2] or trigger
        try:
            result = self.recover_session(context, trigger=trigger)
        except Exception:
            result = None
        try:
            contained = self.recovery.contain_terminal_pairing(
                session=context.session,
                binding=context.binding,
                provider_runtime=self.provider_runtimes.resolve(context.binding),
                turn_id=context.correlation_id,
                trigger=trigger,
                terminal_reason_code=failure_reason,
            )
        except Exception:
            return "provider_state_ambiguous"
        if result is None:
            return contained or "provider_state_ambiguous"
        if not result.recovered:
            return result.reason_code
        return None

    def _read_final_output(self, context, provider_runtime, record) -> str:
        if (
            record.final_output_status not in {"ready", "delivered"}
            or not record.final_output_id
            or not record.final_output_private_ref
            or not record.final_output_sha256
            or record.final_output_size_bytes is None
        ):
            raise HostedAgenticLoopError("provider_state_ambiguous")
        try:
            return self.private_state_service.read_final_output(
                session_id=context.session.session_id,
                adapter_id=context.binding.adapter_id,
                adapter_version=context.binding.adapter_version,
                codec_id=provider_runtime.private_codec.codec_id,
                codec_version=provider_runtime.private_codec.codec_version,
                schema_version=provider_runtime.private_codec.schema_version,
                private_ref=record.final_output_private_ref,
                content_sha256=record.final_output_sha256,
                size_bytes=record.final_output_size_bytes,
            )
        except Exception as error:
            raise HostedAgenticLoopError("provider_state_ambiguous") from error

    @staticmethod
    def _validate_request_pairing(
        request: AgenticModelRequest,
        *,
        pairing_source: ProviderStepJournalRecord | None,
        turn_id: str,
        request_lineage_digest: str,
    ) -> None:
        if pairing_source is None:
            if request.tool_results or any(
                value is not None
                for value in (
                    request.pairing_source_journal_id,
                    request.pairing_source_turn_id,
                    request.pairing_source_request_id,
                )
            ):
                raise HostedAgenticLoopError("provider_pairing_ambiguous")
            return
        state = request.provider_private_state
        if (
            not request.tool_results
            or pairing_source.turn_id != turn_id
            or request.correlation_id != turn_id
            or request.pairing_source_journal_id != pairing_source.journal_id
            or request.pairing_source_turn_id != pairing_source.turn_id
            or request.pairing_source_request_id != pairing_source.request_id
            or pairing_source.request_lineage_digest != request_lineage_digest
            or state is None
            or state.provider_request_id != pairing_source.request_id
            or state.turn_generation != pairing_source.turn_id
        ):
            raise HostedAgenticLoopError("provider_pairing_ambiguous")


def _turn_budget_elapsed(records: list[ProviderStepJournalRecord]) -> float:
    if not records:
        return 0.0
    created_at = min(item.created_at for item in records)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return max(0.0, (datetime.now(tz=UTC) - created_at).total_seconds())
