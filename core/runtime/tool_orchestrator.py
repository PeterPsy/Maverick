"""Runtime facade that journals and invokes existing official tool surfaces."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Literal

from core.cli.models import CliInvocationContext
from core.cli.runner import CliRunner
from core.mcp.models import McpInvocationContext
from core.mcp.runner import McpRunner
from core.runtime.authority import EffectiveRuntimeAuthority
from core.runtime.tool_catalog import (
    RuntimeToolActorContext,
    RuntimeToolCatalog,
    RuntimeToolCatalogBuilder,
    RuntimeToolDescriptor,
)
from core.runtime.tool_errors import RuntimeToolError, RuntimeToolSchemaError
from core.runtime.tool_ledger import RuntimeToolLedger
from core.runtime.tool_models import ToolConfirmationGrant, ToolInvocationRecord
from core.runtime.tool_schema import validate_tool_arguments


@dataclass(frozen=True)
class RuntimeToolConfirmationPolicy:
    """Effective confirmation and output bounds for one turn."""
    policy_revision: str
    require_confirmation_for_mutating: bool
    require_confirmation_for_destructive: bool
    max_tool_result_bytes: int


@dataclass(frozen=True)
class RuntimeToolInvocationOutcome:
    """Redaction-safe result of orchestration; payload remains behind a ref."""
    invocation: ToolInvocationRecord
    confirmation_grant: ToolConfirmationGrant | None = None

    @property
    def awaiting_confirmation(self) -> bool:
        return self.invocation.state == "awaiting_confirmation"


class RuntimeToolOrchestrator:
    """Validate, confirm and execute tool calls with no shadow registry."""
    def __init__(
        self,
        *,
        catalog_builder: RuntimeToolCatalogBuilder,
        ledger: RuntimeToolLedger,
    ) -> None:
        self.catalog_builder = catalog_builder
        self.ledger = ledger
        self.cli_runner = CliRunner(catalog_builder.cli_registry)
        self.mcp_runner = McpRunner(catalog_builder.mcp_registry)
    def materialize(
        self, *, authority: EffectiveRuntimeAuthority, context: RuntimeToolActorContext
    ) -> RuntimeToolCatalog:
        return self.catalog_builder.build(authority=authority, context=context)
    def invoke_provider_tool(
        self,
        *,
        provider_tool_name: str,
        provider_tool_call_id: str,
        arguments: dict[str, object],
        authority: EffectiveRuntimeAuthority,
        context: RuntimeToolActorContext,
        turn_id: str,
        policy: RuntimeToolConfirmationPolicy,
    ) -> RuntimeToolInvocationOutcome:
        """Persist before validation and advance at most one serialized tool call."""
        catalog = self.materialize(authority=authority, context=context)
        descriptor = catalog.by_provider_name(provider_tool_name)
        record, created = self.ledger.propose(
            workspace_id=context.workspace_id,
            session_id=context.session_id,
            turn_id=turn_id,
            provider_tool_call_id=provider_tool_call_id,
            tool_handle=descriptor.handle,
            arguments=arguments,
            effect_class=descriptor.effect_class,
            policy_revision=policy.policy_revision,
            authority_digest=authority.authority_digest,
        )
        if not created and record.state == "executing":
            record = self.ledger.recover_executing(record, safe_to_retry=descriptor.safe_to_retry)
        if record.state in {
            "awaiting_confirmation",
            "denied",
            "succeeded",
            "failed",
            "cancelled",
            "expired",
            "execution_unknown",
        }:
            return RuntimeToolInvocationOutcome(record)
        if record.state == "proposed":
            record = self.ledger.transition(record, "validating")
        if record.state == "validating":
            try:
                validate_tool_arguments(descriptor.original_input_schema, arguments)
            except RuntimeToolSchemaError as error:
                record = self.ledger.transition(record, "denied", failure_reason=error.reason_code)
                return RuntimeToolInvocationOutcome(record)
            record = self.ledger.transition(record, "validated")
        if record.state == "validated":
            if self._requires_confirmation(descriptor, policy):
                return RuntimeToolInvocationOutcome(
                    self.ledger.transition(record, "awaiting_confirmation")
                )
            record = self.ledger.transition(record, "authorized")
        return RuntimeToolInvocationOutcome(
            self._execute(record, descriptor=descriptor, context=context, policy=policy)
        )
    def decide_confirmation(
        self,
        *,
        invocation_id: str,
        decision: Literal["approve", "deny"],
        arguments_digest: str,
        expected_invocation_revision: int,
        confirming_actor_id: str,
        policy: RuntimeToolConfirmationPolicy,
    ) -> RuntimeToolInvocationOutcome:
        record, grant = self.ledger.confirm(
            invocation_id=invocation_id,
            decision=decision,
            arguments_digest=arguments_digest,
            expected_invocation_revision=expected_invocation_revision,
            confirming_actor_id=confirming_actor_id,
            policy_revision=policy.policy_revision,
        )
        return RuntimeToolInvocationOutcome(record, grant)
    def resume_confirmed(
        self,
        *,
        invocation_id: str,
        grant_id: str,
        authority: EffectiveRuntimeAuthority,
        context: RuntimeToolActorContext,
        policy: RuntimeToolConfirmationPolicy,
    ) -> RuntimeToolInvocationOutcome:
        """Recompute authority, consume the grant, then cross the effect boundary."""
        catalog = self.materialize(authority=authority, context=context)
        pending = self.ledger.store.get_tool_invocation(invocation_id)
        descriptor = catalog.by_handle(pending.resolved_tool_handle)
        record = self.ledger.authorize(invocation_id=invocation_id, grant_id=grant_id)
        if record.state == "expired":
            return RuntimeToolInvocationOutcome(record)
        if record.state in {"executing", "succeeded", "failed", "cancelled", "execution_unknown"}:
            return RuntimeToolInvocationOutcome(record)
        if record.state != "authorized":
            raise RuntimeToolError("tool_confirmation_invalid")
        return RuntimeToolInvocationOutcome(
            self._execute(record, descriptor=descriptor, context=context, policy=policy)
        )
    def recover_invocation(
        self,
        *,
        invocation_id: str,
        authority: EffectiveRuntimeAuthority,
        context: RuntimeToolActorContext,
    ) -> RuntimeToolInvocationOutcome:
        """Reconcile an interrupted execution without replaying ambiguous effects."""
        catalog = self.materialize(authority=authority, context=context)
        record = self.ledger.store.get_tool_invocation(invocation_id)
        descriptor = catalog.by_handle(record.resolved_tool_handle)
        return RuntimeToolInvocationOutcome(
            self.ledger.recover_executing(record, safe_to_retry=descriptor.safe_to_retry)
        )
    def _execute(
        self,
        record: ToolInvocationRecord,
        *,
        descriptor: RuntimeToolDescriptor,
        context: RuntimeToolActorContext,
        policy: RuntimeToolConfirmationPolicy,
    ) -> ToolInvocationRecord:
        if record.state != "authorized":
            return record
        executing = self.ledger.transition(record, "executing")
        crossed_effect_boundary = False
        try:
            arguments = self.ledger.load_arguments(executing)
            validate_tool_arguments(descriptor.original_input_schema, arguments)
            crossed_effect_boundary = True
            result = self._invoke_surface(
                descriptor=descriptor,
                arguments=arguments,
                context=context,
                idempotency_key=(executing.idempotency_key if descriptor.supports_idempotency else None),
            )
            encoded = json.dumps(
                result, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
            ).encode("utf-8")
            if len(encoded) > policy.max_tool_result_bytes:
                raise RuntimeToolError("tool_result_too_large")
            if descriptor.output_schema is not None:
                validate_tool_arguments(descriptor.output_schema, result)
            private_ref = self.ledger.private_payload_store.put(
                workspace_id=executing.workspace_id,
                session_id=executing.session_id,
                payload=encoded,
            )
            summary = {
                "root_type": "object",
                "field_count": len(result),
                "serialized_bytes": len(encoded),
            }
            return self.ledger.transition(
                executing,
                "succeeded",
                result_private_ref=private_ref,
                result_summary=summary,
            )
        except RuntimeToolError as error:
            state = (
                "execution_unknown"
                if crossed_effect_boundary and descriptor.effect_class != "read"
                else "failed"
            )
            return self.ledger.transition(executing, state, failure_reason=error.reason_code)
        except Exception:
            state = (
                "execution_unknown"
                if crossed_effect_boundary and descriptor.effect_class != "read"
                else "failed"
            )
            return self.ledger.transition(executing, state, failure_reason="tool_execution_failed")

    def _invoke_surface(
        self,
        *,
        descriptor: RuntimeToolDescriptor,
        arguments: dict[str, object],
        context: RuntimeToolActorContext,
        idempotency_key: str | None,
    ) -> dict[str, object]:
        caller_kind = "sandbox_agent" if context.execution_mode == "sandbox" else "full_access_agent"
        if descriptor.surface_kind == "cli":
            return self.cli_runner.run_command(
                command_id=descriptor.source_id,
                arguments=arguments,
                context=CliInvocationContext(
                    caller_kind=caller_kind,
                    workspace_id=context.workspace_id,
                    agent_id=context.agent_id,
                    effective_mode=context.execution_mode,
                    platform_role=context.platform_role,
                    user_id=context.actor_id,
                    workspace_role=context.workspace_role,
                    runtime_session_id=context.session_id,
                    idempotency_key=idempotency_key,
                ),
            )
        if descriptor.surface_kind == "mcp":
            return self.mcp_runner.call_tool(
                tool_name=descriptor.source_id,
                arguments=arguments,
                context=McpInvocationContext(
                    caller_kind=caller_kind,
                    workspace_id=context.workspace_id,
                    agent_id=context.agent_id,
                    effective_mode=context.execution_mode,
                    platform_role=context.platform_role,
                    user_id=context.actor_id,
                    workspace_role=context.workspace_role,
                    runtime_session_id=context.session_id,
                    idempotency_key=idempotency_key,
                ),
            )
        if descriptor.surface_kind == "app-interface":
            resolver = self.catalog_builder.app_interface_resolver
            if resolver is None:
                raise RuntimeToolError("tool_interface_unavailable")
            return resolver.invoke_tool_surface(
                handle=descriptor.handle,
                arguments=arguments,
                context=context,
                idempotency_key=idempotency_key,
            )
        surface = next(
            (item for item in self.catalog_builder.core_capabilities if item.definition.handle == descriptor.handle),
            None,
        )
        if surface is None:
            raise RuntimeToolError("tool_core_capability_unavailable")
        return surface.handler(arguments, context, idempotency_key)

    @staticmethod
    def _requires_confirmation(
        descriptor: RuntimeToolDescriptor, policy: RuntimeToolConfirmationPolicy
    ) -> bool:
        return (
            descriptor.effect_class == "mutating" and policy.require_confirmation_for_mutating
        ) or (
            descriptor.effect_class == "destructive" and policy.require_confirmation_for_destructive
        )
