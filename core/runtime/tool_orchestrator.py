"""Runtime facade that journals and invokes existing official tool surfaces."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
import hashlib
import json
from threading import Event, RLock
import time
from typing import Literal

from core.egress.classification import (
    CanonicalSourceClassification,
    derive_content_classification,
    fail_closed_classification,
    join_classifications,
)
from core.cli.models import CliInvocationContext
from core.cli.runner import CliRunner
from core.mcp.models import McpInvocationContext
from core.mcp.runner import McpRunner
from core.runtime.authority import EffectiveRuntimeAuthority
from core.runtime.classification_authority import (
    revalidate_canonical_classification,
)
from core.runtime.content_data_classification import (
    narrow_runtime_content_classification,
)
from core.runtime.tool_catalog import (
    RuntimeToolActorContext,
    RuntimeToolCatalog,
    RuntimeToolCatalogBuilder,
    RuntimeToolDescriptor,
    RuntimeToolResultPreflightDecision,
    RuntimeToolSurfaceResult,
)
from core.runtime.tool_errors import (
    RuntimeToolError,
    RuntimeToolRevisionError,
    RuntimeToolSchemaError,
)
from core.runtime.tool_ledger import RuntimeToolLedger
from core.runtime.output_compaction.cli_result import compact_runtime_cli_result
from core.runtime.runtime_cancellation import RuntimeCancellationSignal
from core.runtime.tool_models import ToolConfirmationGrant, ToolInvocationRecord
from core.runtime.tool_result_artifacts import TOOL_RESULT_ARTIFACT_READ_HANDLE
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


@dataclass
class RuntimeToolExecutionControl:
    """Cooperative cancellation and a hard commit deadline for one tool effect."""

    deadline_monotonic: float
    deadline_utc: datetime
    execution_lease_id: str
    cancellation: Event
    monotonic: Callable[[], float] = time.monotonic
    external_cancellation: RuntimeCancellationSignal | None = None
    cancellation_reason: str = "runtime_cancelled"
    _callbacks: dict[int, Callable[[], None]] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )
    _callback_lock: RLock = field(
        default_factory=RLock,
        init=False,
        repr=False,
    )
    _next_callback_id: int = field(default=0, init=False, repr=False)
    _had_cancellation_callback: bool = field(
        default=False,
        init=False,
        repr=False,
    )
    _completed: bool = field(default=False, init=False, repr=False)

    def cancel(self, reason_code: str) -> None:
        with self._callback_lock:
            if not self.cancellation.is_set():
                self.cancellation_reason = reason_code
                self.cancellation.set()
            callbacks = tuple(self._callbacks.values())
            self._callbacks.clear()
        for callback in callbacks:
            try:
                callback()
            except Exception:
                pass

    def check(self) -> None:
        if (
            self.external_cancellation is not None
            and self.external_cancellation.is_set()
        ):
            raise RuntimeToolError("runtime_cancelled")
        if self.cancellation.is_set():
            raise RuntimeToolError(self.cancellation_reason)
        if self.monotonic() >= self.deadline_monotonic:
            raise RuntimeToolError("agent_finalization_time_reserve_reached")

    def add_cancellation_callback(self, callback: Callable[[], None]) -> None:
        """Register cleanup that runs synchronously when this lease is fenced."""
        call_now = False
        with self._callback_lock:
            self._had_cancellation_callback = True
            if self.cancellation.is_set():
                call_now = True
            elif not self._completed:
                callback_id = self._next_callback_id
                self._next_callback_id += 1
                self._callbacks[callback_id] = callback
        if call_now:
            callback()

    def require_quiescence(self) -> None:
        """Fence a cooperative surface even before it registers its cleanup."""
        with self._callback_lock:
            self._had_cancellation_callback = True

    def run_if_active(self, action: Callable[[], object]) -> object:
        """Cross one effect boundary atomically with respect to cancellation."""
        def run() -> object:
            with self._callback_lock:
                self.check()
                return action()

        if self.external_cancellation is None:
            return run()
        return self.external_cancellation.run_if_active(
            run,
            cancelled=self._raise_external_cancellation,
        )

    @staticmethod
    def _raise_external_cancellation() -> object:
        raise RuntimeToolError("runtime_cancelled")

    def complete(self) -> None:
        """Release callbacks only after the authoritative ledger commit."""
        with self._callback_lock:
            self._completed = True
            self._callbacks.clear()

    @property
    def requires_quiescence(self) -> bool:
        with self._callback_lock:
            return self._had_cancellation_callback


class RuntimeToolOrchestrator:
    """Validate, confirm and execute tool calls with no shadow registry."""
    def __init__(
        self,
        *,
        catalog_builder: RuntimeToolCatalogBuilder,
        ledger: RuntimeToolLedger,
        classification_authority_store=None,
    ) -> None:
        self.catalog_builder = catalog_builder
        self.ledger = ledger
        self.classification_authority_store = classification_authority_store
        self.cli_runner = CliRunner(catalog_builder.cli_registry)
        self.mcp_runner = McpRunner(catalog_builder.mcp_registry)

    def persisted_result_classification(
        self,
        record: ToolInvocationRecord,
    ) -> CanonicalSourceClassification:
        """Rebuild and live-check the authority pinned to one durable result."""
        classification = CanonicalSourceClassification(
            data_class=record.result_data_class,  # type: ignore[arg-type]
            provenance=record.result_provenance,  # type: ignore[arg-type]
            trust_level=record.result_trust_level,  # type: ignore[arg-type]
            source_ref=record.result_source_ref,
            source_revision=record.result_source_revision,
            source_digest=record.result_source_digest,
            resource_identity=record.result_resource_identity,
            classification_revision=record.result_classification_revision,
            classification_authority_id=(
                record.result_classification_authority_id
            ),
            classification_authority_kind=(
                record.result_classification_authority_kind
            ),
            classification_authority_ref=(
                record.result_classification_authority_ref
            ),
            classification_authority_revision=(
                record.result_classification_authority_revision
            ),
            classification_authority_digest=(
                record.result_classification_authority_digest
            ),
            classification_authority_policy_revision=(
                record.result_classification_authority_policy_revision
            ),
            classification_authority_bound=(
                record.result_classification_authority_bound
            ),
        )
        if self.classification_authority_store is None:
            return join_classifications((classification,)).sources[0]
        return revalidate_canonical_classification(
            self.classification_authority_store,
            workspace_id=record.workspace_id,
            classification=classification,
        )

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
        """Compatibility facade over observe, disposition, and execution phases."""
        catalog = self.materialize(authority=authority, context=context)
        outcome = self.observe_provider_tool(
            provider_tool_name=provider_tool_name,
            provider_tool_call_id=provider_tool_call_id,
            arguments=arguments,
            provider_request_id="legacy-provider-request",
            provider_event_ordinal=0,
            provider_call_index=0,
            authority=authority,
            context=context,
            turn_id=turn_id,
            policy=policy,
        )
        prepared = self.prepare_observed_tool(
            outcome.invocation,
            requested_catalog=catalog,
            authority=authority,
            context=context,
            policy=policy,
        )
        if prepared.invocation.state != "authorized":
            return prepared
        return self.execute_authorized(
            prepared.invocation,
            authority=authority,
            context=context,
            policy=policy,
        )

    def observe_provider_tool(
        self,
        *,
        provider_tool_name: str,
        provider_tool_call_id: str,
        arguments: dict[str, object] | bytes,
        provider_request_id: str,
        provider_event_ordinal: int,
        provider_call_index: int,
        authority: EffectiveRuntimeAuthority,
        context: RuntimeToolActorContext,
        turn_id: str,
        policy: RuntimeToolConfirmationPolicy,
    ) -> RuntimeToolInvocationOutcome:
        """Persist a preliminary proposal before catalog, schema, policy, or budget."""
        record, _created = self.ledger.propose(
            workspace_id=context.workspace_id,
            session_id=context.session_id,
            turn_id=turn_id,
            provider_tool_call_id=provider_tool_call_id,
            arguments=arguments,
            policy_revision=policy.policy_revision,
            authority_digest=authority.authority_digest,
            provider_safe_name=provider_tool_name,
            provider_request_id=provider_request_id,
            provider_event_ordinal=provider_event_ordinal,
            provider_call_index=provider_call_index,
        )
        return RuntimeToolInvocationOutcome(record)

    def deny_observed_tool(
        self,
        record: ToolInvocationRecord,
        *,
        resolution_status,
        failure_reason: str,
    ) -> RuntimeToolInvocationOutcome:
        return RuntimeToolInvocationOutcome(
            self.ledger.deny(
                record,
                resolution_status=resolution_status,
                failure_reason=failure_reason,
            )
        )

    def prepare_observed_tool(
        self,
        record: ToolInvocationRecord,
        *,
        requested_catalog: RuntimeToolCatalog,
        authority: EffectiveRuntimeAuthority,
        context: RuntimeToolActorContext,
        policy: RuntimeToolConfirmationPolicy,
    ) -> RuntimeToolInvocationOutcome:
        """Resolve and persist a disposition without crossing the effect boundary."""
        if record.state == "executing":
            record = self.ledger.recover_executing(
                record,
                safe_to_retry=record.safe_to_retry,
            )
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
        try:
            requested_descriptor = requested_catalog.by_provider_name(
                record.provider_safe_name
            )
        except RuntimeToolError:
            return self.deny_observed_tool(
                record,
                resolution_status="unknown_tool",
                failure_reason="tool_not_found",
            )
        live_catalog = self.materialize(authority=authority, context=context)
        try:
            descriptor = live_catalog.by_handle(requested_descriptor.handle)
        except RuntimeToolError:
            revoked = requested_descriptor.handle not in authority.allowed_tool_handles
            return self.deny_observed_tool(
                record,
                resolution_status="revoked" if revoked else "not_authorized",
                failure_reason="tool_authority_revoked" if revoked else "tool_not_authorized",
            )
        record = self.ledger.resolve(
            record,
            tool_handle=descriptor.handle,
            effect_class=descriptor.effect_class,
            safe_to_retry=descriptor.safe_to_retry,
        )
        if record.state == "proposed":
            record = self.ledger.transition(record, "validating")
        if record.state == "validating":
            try:
                if record.arguments_summary.get("root_type") == "malformed_json":
                    raise RuntimeToolSchemaError("tool_arguments_invalid")
                arguments = self.ledger.load_arguments(record)
                validate_tool_arguments(descriptor.original_input_schema, arguments)
            except RuntimeToolSchemaError as error:
                return self.deny_observed_tool(
                    record,
                    resolution_status="schema_denied",
                    failure_reason=error.reason_code,
                )
            except RuntimeToolError as error:
                return self.deny_observed_tool(
                    record,
                    resolution_status="schema_denied",
                    failure_reason=error.reason_code,
                )
            preflight = self.catalog_builder.result_preflight_resolver
            if preflight is not None:
                try:
                    preflight_decision = preflight(
                        descriptor.handle,
                        arguments,
                        context,
                    )
                except Exception:
                    return self.deny_observed_tool(
                        record,
                        resolution_status="not_authorized",
                        failure_reason="tool_result_egress_not_guaranteed",
                    )
                if (
                    preflight_decision is not None
                    and (
                        not isinstance(
                            preflight_decision,
                            RuntimeToolResultPreflightDecision,
                        )
                        or not preflight_decision.admitted_before_effect
                        or (
                            preflight_decision.guaranteed_data_class is not None
                            and preflight_decision.guaranteed_data_class
                            not in authority.allowed_remote_data_classes
                        )
                    )
                ):
                    return self.deny_observed_tool(
                        record,
                        resolution_status="not_authorized",
                        failure_reason="tool_result_egress_not_guaranteed",
                    )
            record = self.ledger.transition(record, "validated")
        if record.state == "validated":
            if self._requires_confirmation(descriptor, policy):
                return RuntimeToolInvocationOutcome(
                    self.ledger.transition(record, "awaiting_confirmation")
                )
            record = self.ledger.transition(record, "authorized")
        return RuntimeToolInvocationOutcome(record)

    def execute_authorized(
        self,
        record: ToolInvocationRecord,
        *,
        authority: EffectiveRuntimeAuthority,
        context: RuntimeToolActorContext,
        policy: RuntimeToolConfirmationPolicy,
        control: RuntimeToolExecutionControl | None = None,
    ) -> RuntimeToolInvocationOutcome:
        """Fence and execute one authorized invocation synchronously."""
        started = self.start_authorized(
            record,
            authority=authority,
            context=context,
            control=control,
        )
        return self.execute_started(
            started.invocation,
            authority=authority,
            context=context,
            policy=policy,
            control=control,
        )

    def start_authorized(
        self,
        record: ToolInvocationRecord,
        *,
        authority: EffectiveRuntimeAuthority,
        context: RuntimeToolActorContext,
        control: RuntimeToolExecutionControl | None = None,
    ) -> RuntimeToolInvocationOutcome:
        """Fence the effect boundary before dispatching synchronous tool code."""
        if record.state != "authorized":
            return RuntimeToolInvocationOutcome(record)
        if record.resolved_tool_handle is None:
            raise RuntimeToolError("tool_not_authorized")
        self.materialize(
            authority=authority,
            context=context,
        ).by_handle(record.resolved_tool_handle)
        return RuntimeToolInvocationOutcome(
            self.ledger.transition(
                record,
                "executing",
                execution_lease_id=(
                    control.execution_lease_id if control is not None else None
                ),
                execution_lease_expires_at=(
                    control.deadline_utc if control is not None else None
                ),
            )
        )

    def execute_started(
        self,
        record: ToolInvocationRecord,
        *,
        authority: EffectiveRuntimeAuthority,
        context: RuntimeToolActorContext,
        policy: RuntimeToolConfirmationPolicy,
        control: RuntimeToolExecutionControl | None = None,
    ) -> RuntimeToolInvocationOutcome:
        """Invoke a fenced tool and commit a result only while its lease is live."""
        if record.state != "executing":
            return RuntimeToolInvocationOutcome(record)
        if record.resolved_tool_handle is None:
            raise RuntimeToolError("tool_not_authorized")
        try:
            descriptor = self.materialize(
                authority=authority,
                context=context,
            ).by_handle(record.resolved_tool_handle)
        except RuntimeToolError as error:
            return RuntimeToolInvocationOutcome(
                self._persist_execution_failure(
                    record,
                    state="failed",
                    reason_code=error.reason_code,
                )
            )
        except Exception:
            return RuntimeToolInvocationOutcome(
                self._persist_execution_failure(
                    record,
                    state="failed",
                    reason_code="tool_execution_failed",
                )
            )
        return RuntimeToolInvocationOutcome(
            self._execute_started(
                record,
                descriptor=descriptor,
                context=context,
                policy=policy,
                control=control,
            )
        )

    def interrupt_started_execution(
        self,
        record: ToolInvocationRecord,
        *,
        failure_reason: str,
    ) -> RuntimeToolInvocationOutcome:
        """Fence a timed-out worker so a late result cannot become authoritative."""
        current = self.ledger.store.get_tool_invocation(record.invocation_id)
        if current.state in {
            "denied",
            "succeeded",
            "failed",
            "cancelled",
            "expired",
            "execution_unknown",
        }:
            return RuntimeToolInvocationOutcome(current)
        if current.state != "executing":
            raise RuntimeToolError("tool_state_transition_invalid")
        state = "failed" if current.effect_class == "read" else "execution_unknown"
        return RuntimeToolInvocationOutcome(
            self._persist_execution_failure(
                current,
                state=state,
                reason_code=failure_reason,
            )
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
        """Compatibility facade that authorizes and immediately executes."""
        authorized = self.authorize_confirmed(
            invocation_id=invocation_id,
            grant_id=grant_id,
            authority=authority,
            context=context,
        )
        if authorized.invocation.state != "authorized":
            return authorized
        return self.execute_authorized(
            authorized.invocation,
            authority=authority,
            context=context,
            policy=policy,
        )

    def authorize_confirmed(
        self,
        *,
        invocation_id: str,
        grant_id: str,
        authority: EffectiveRuntimeAuthority,
        context: RuntimeToolActorContext,
    ) -> RuntimeToolInvocationOutcome:
        """Consume confirmation and recompute authority without executing."""
        catalog = self.materialize(authority=authority, context=context)
        pending = self.ledger.store.get_tool_invocation(invocation_id)
        if pending.resolved_tool_handle is None:
            raise RuntimeToolError("tool_confirmation_invalid")
        descriptor = catalog.by_handle(pending.resolved_tool_handle)
        record = self.ledger.authorize(invocation_id=invocation_id, grant_id=grant_id)
        if record.state == "expired":
            return RuntimeToolInvocationOutcome(record)
        if record.state in {"executing", "succeeded", "failed", "cancelled", "execution_unknown"}:
            return RuntimeToolInvocationOutcome(record)
        if record.state != "authorized":
            raise RuntimeToolError("tool_confirmation_invalid")
        if descriptor.handle != record.resolved_tool_handle:
            raise RuntimeToolError("tool_confirmation_invalid")
        return RuntimeToolInvocationOutcome(record)
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
        if record.resolved_tool_handle is None:
            raise RuntimeToolError("tool_not_authorized")
        descriptor = catalog.by_handle(record.resolved_tool_handle)
        return RuntimeToolInvocationOutcome(
            self.ledger.recover_executing(record, safe_to_retry=descriptor.safe_to_retry)
        )
    def _execute_started(
        self,
        record: ToolInvocationRecord,
        *,
        descriptor: RuntimeToolDescriptor,
        context: RuntimeToolActorContext,
        policy: RuntimeToolConfirmationPolicy,
        control: RuntimeToolExecutionControl | None,
    ) -> ToolInvocationRecord:
        if record.state != "executing":
            return record
        executing = record
        crossed_effect_boundary = False
        try:
            if control is not None:
                control.check()
            arguments = self.ledger.load_arguments(executing)
            validate_tool_arguments(descriptor.original_input_schema, arguments)
            if control is not None:
                control.check()
            crossed_effect_boundary = True
            surface_result = self._invoke_surface(
                descriptor=descriptor,
                arguments=arguments,
                context=context,
                idempotency_key=(executing.idempotency_key if descriptor.supports_idempotency else None),
                control=control,
            )
            if control is not None:
                control.check()
            if isinstance(surface_result, RuntimeToolSurfaceResult):
                result = surface_result.payload
                classification = join_classifications(
                    (surface_result.classification,)
                ).sources[0]
            else:
                result = surface_result
                classification = fail_closed_classification(
                    provenance="tool_result",
                    source_ref=descriptor.handle,
                )
            # Validate the capability result before the shared CLI compactor
            # projects it into the bounded transport representation.  The
            # projection is intentionally generic and need not preserve an
            # app-specific output schema verbatim.
            if descriptor.output_schema is not None:
                validate_tool_arguments(descriptor.output_schema, result)
            resolver = self.catalog_builder.result_classification_resolver
            if resolver is not None:
                try:
                    resolved = resolver(
                        descriptor.handle,
                        arguments,
                        result,
                        context,
                    )
                except Exception:
                    resolved = fail_closed_classification(
                        provenance="tool_result",
                        source_ref=descriptor.handle,
                    )
                if isinstance(resolved, RuntimeToolSurfaceResult):
                    result = resolved.payload
                    classification = join_classifications(
                        (resolved.classification,)
                    ).sources[0]
                elif isinstance(resolved, CanonicalSourceClassification):
                    classification = join_classifications((resolved,)).sources[0]
                elif resolved is not None:
                    classification = fail_closed_classification(
                        provenance="tool_result",
                        source_ref=descriptor.handle,
                    )
            encoded_original = json.dumps(
                result,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            classification = narrow_runtime_content_classification(
                classification,
                encoded_original,
                content_type="application/json",
            )
            if len(encoded_original) > policy.max_tool_result_bytes:
                raise RuntimeToolError("tool_result_too_large")
            if descriptor.handle == TOOL_RESULT_ARTIFACT_READ_HANDLE:
                projected_result = dict(result)
            else:
                try:
                    projected_result = compact_runtime_cli_result(
                        result,
                        argv=(descriptor.handle,),
                        runtime_session_id=context.session_id,
                    )
                except Exception as error:
                    raise RuntimeToolError("tool_output_compaction_failed") from error
            encoded = json.dumps(
                projected_result,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            classification = narrow_runtime_content_classification(
                classification,
                encoded,
                content_type="application/json",
            )
            classification = derive_content_classification(
                content=encoded,
                provenance="tool_result",
                source_ref=classification.source_ref or descriptor.handle,
                sources=(classification,),
            )
            summary = {
                "root_type": "object",
                "field_count": len(projected_result),
                "serialized_bytes": len(encoded),
                "original_serialized_bytes": len(encoded_original),
                "artifact_available": encoded != encoded_original,
                "data_class": classification.data_class,
                "trust_level": classification.trust_level,
                "source_revision": classification.source_revision,
                "resource_identity": classification.resource_identity,
                "classification_revision": classification.classification_revision,
            }
            if control is not None:
                control.check()
            succeeded = self._persist_execution_success(
                executing,
                encoded=encoded,
                artifact_encoded=(
                    encoded_original if encoded != encoded_original else None
                ),
                result_summary=summary,
                result_classification=classification,
                control=control,
            )
            return succeeded
        except RuntimeToolError as error:
            if control is not None and control.requires_quiescence:
                control.cancel(error.reason_code)
            state = (
                "execution_unknown"
                if crossed_effect_boundary and descriptor.effect_class != "read"
                else "failed"
            )
            failed = self._persist_execution_failure(
                executing,
                state=state,
                reason_code=error.reason_code,
            )
            return failed
        except Exception:
            if control is not None and control.requires_quiescence:
                control.cancel("tool_execution_failed")
            state = (
                "execution_unknown"
                if crossed_effect_boundary and descriptor.effect_class != "read"
                else "failed"
            )
            failed = self._persist_execution_failure(
                executing,
                state=state,
                reason_code="tool_execution_failed",
            )
            return failed
        finally:
            if control is not None:
                control.complete()

    def _persist_execution_success(
        self,
        executing: ToolInvocationRecord,
        *,
        encoded: bytes,
        artifact_encoded: bytes | None,
        result_summary: dict[str, object],
        result_classification,
        control: RuntimeToolExecutionControl | None,
    ) -> ToolInvocationRecord:
        private_ref = self.ledger.private_payload_store.put(
            workspace_id=executing.workspace_id,
            session_id=executing.session_id,
            payload=encoded,
        )
        artifact_ref = None
        try:
            if artifact_encoded is not None:
                artifact_ref = self.ledger.private_payload_store.put(
                    workspace_id=executing.workspace_id,
                    session_id=executing.session_id,
                    payload=artifact_encoded,
                )
            if control is not None:
                control.check()
            return self.ledger.transition(
                executing,
                "succeeded",
                result_private_ref=private_ref,
                result_summary=result_summary,
                result_classification=result_classification,
                result_artifact_private_ref=artifact_ref,
                result_artifact_sha256=(
                    ""
                    if artifact_encoded is None
                    else hashlib.sha256(artifact_encoded).hexdigest()
                ),
                result_artifact_size_bytes=(
                    None if artifact_encoded is None else len(artifact_encoded)
                ),
                require_active_execution_lease_id=(
                    control.execution_lease_id if control is not None else None
                ),
            )
        except RuntimeToolRevisionError:
            self.ledger.private_payload_store.delete(
                workspace_id=executing.workspace_id,
                session_id=executing.session_id,
                private_ref=private_ref,
            )
            if artifact_ref is not None:
                self.ledger.private_payload_store.delete(
                    workspace_id=executing.workspace_id,
                    session_id=executing.session_id,
                    private_ref=artifact_ref,
                )
            current = self.ledger.store.get_tool_invocation(executing.invocation_id)
            if current.state in {
                "succeeded",
                "failed",
                "cancelled",
                "execution_unknown",
            } and current.result_id is not None:
                return current
            raise
        except Exception:
            self.ledger.private_payload_store.delete(
                workspace_id=executing.workspace_id,
                session_id=executing.session_id,
                private_ref=private_ref,
            )
            if artifact_ref is not None:
                self.ledger.private_payload_store.delete(
                    workspace_id=executing.workspace_id,
                    session_id=executing.session_id,
                    private_ref=artifact_ref,
                )
            raise

    def _persist_execution_failure(
        self,
        executing: ToolInvocationRecord,
        *,
        state,
        reason_code: str,
    ) -> ToolInvocationRecord:
        encoded = json.dumps(
            {"error": reason_code},
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if reason_code not in {
            "agent_finalization_time_reserve_reached",
            "runtime_cancelled",
        }:
            return self._persist_private_execution_failure(
                executing,
                state=state,
                reason_code=reason_code,
                encoded=encoded,
            )
        try:
            return self.ledger.transition(
                executing,
                state,
                failure_reason=reason_code,
                result_summary={
                    "root_type": "object",
                    "field_count": 1,
                    "serialized_bytes": len(encoded),
                    "is_error": True,
                },
                deterministic_error_result=True,
            )
        except RuntimeToolRevisionError:
            current = self.ledger.store.get_tool_invocation(executing.invocation_id)
            if current.state in {
                "succeeded",
                "failed",
                "cancelled",
                "execution_unknown",
            } and current.result_id is not None:
                return current
            raise

    def _persist_private_execution_failure(
        self,
        executing: ToolInvocationRecord,
        *,
        state,
        reason_code: str,
        encoded: bytes,
    ) -> ToolInvocationRecord:
        private_ref = self.ledger.private_payload_store.put(
            workspace_id=executing.workspace_id,
            session_id=executing.session_id,
            payload=encoded,
        )
        try:
            return self.ledger.transition(
                executing,
                state,
                failure_reason=reason_code,
                result_private_ref=private_ref,
                result_summary={
                    "root_type": "object",
                    "field_count": 1,
                    "serialized_bytes": len(encoded),
                    "is_error": True,
                },
            )
        except RuntimeToolRevisionError:
            self.ledger.private_payload_store.delete(
                workspace_id=executing.workspace_id,
                session_id=executing.session_id,
                private_ref=private_ref,
            )
            current = self.ledger.store.get_tool_invocation(executing.invocation_id)
            if current.state in {
                "succeeded",
                "failed",
                "cancelled",
                "execution_unknown",
            } and current.result_id is not None:
                return current
            raise
        except Exception:
            self.ledger.private_payload_store.delete(
                workspace_id=executing.workspace_id,
                session_id=executing.session_id,
                private_ref=private_ref,
            )
            raise

    def _invoke_surface(
        self,
        *,
        descriptor: RuntimeToolDescriptor,
        arguments: dict[str, object],
        context: RuntimeToolActorContext,
        idempotency_key: str | None,
        control: RuntimeToolExecutionControl | None,
    ) -> dict[str, object] | RuntimeToolSurfaceResult:
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
        return surface.handler(
            arguments,
            replace(context, execution_control=control),
            idempotency_key,
        )

    @staticmethod
    def _requires_confirmation(
        descriptor: RuntimeToolDescriptor, policy: RuntimeToolConfirmationPolicy
    ) -> bool:
        return (
            descriptor.effect_class == "mutating" and policy.require_confirmation_for_mutating
        ) or (
            descriptor.effect_class == "destructive" and policy.require_confirmation_for_destructive
        )
