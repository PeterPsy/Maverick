"""Production composition for the Core-owned hosted agentic runtime."""

from __future__ import annotations

import hashlib
from pathlib import Path

from core.authorization.errors import AuthorizationError
from core.cli.models import CliInvocationContext
from core.egress.agentic_transforms import canonical_egress_content
from core.mcp.models import McpInvocationContext
from core.providers.agentic_protocol import EphemeralCredential
from core.providers.errors import CapabilityCertificateError, ProviderError
from core.providers.provider_credentials import resolve_provider_binding
from core.providers.provider_registry import ProviderRegistry
from core.runtime.authority import (
    intersect_runtime_policies,
)
from core.runtime.attachment_projection import runtime_attachment_read_fences
from core.runtime.authority_service import (
    resolve_runtime_authority_snapshot,
    revalidate_runtime_authority_snapshot,
)
from core.runtime.filesystem_mutation_lineage import (
    resolve_filesystem_mutation_lineage,
)
from core.runtime.classification_authority import (
    revalidate_hosted_content_classification,
)
from core.runtime.hosted_agentic_engine import (
    HostedAgenticEngineAdapter,
    build_hosted_turn_status_callback,
)
from core.runtime.hosted_agentic_loop import HostedAgenticLoop
from core.runtime.hosted_agentic_models import (
    HostedAgenticLoopError,
    HostedContentClassification,
    HostedContentClassifier,
)
from core.runtime.hosted_agentic_request import (
    HOSTED_TOOL_USE_INSTRUCTION,
    HostedAgenticRequestBuilder,
)
from core.runtime.hosted_tool_process_registry import HostedToolProcessRegistry
from core.runtime.hosted_tool_result_admission import (
    build_hosted_tool_result_preflight_resolver,
    build_hosted_tool_result_admission_resolver,
)
from core.runtime.public_content_classification import (
    resolve_runtime_public_resource_classification,
)
from core.runtime.public_content_authority_store import (
    runtime_public_content_authority_for_workspace,
)
from core.runtime.hosted_agentic_policy import authorized_core_tool_handles
from core.runtime.hosted_runtime_registry_builder import (
    build_hosted_provider_runtime_registry,
)
from core.runtime.runtime_actor import resolve_runtime_actor_roles
from core.runtime.semantic_envelope import HostedSemanticEnvelopeCompiler
from core.runtime.tool_catalog import RuntimeToolActorContext, RuntimeToolCatalogBuilder
from core.runtime.tool_core_capabilities import build_core_runtime_tool_capabilities
from core.runtime.tool_orchestrator import RuntimeToolOrchestrator
from core.workspaces.data_governance import resource_classification_for_observation
from core.secrets.models import SecretResolutionContext
from core.secrets.secret_resolution import resolve_secret_for_runtime


HOSTED_AGENTIC_ENGINE_ID = "maverick-tool-loop"
HOSTED_AGENTIC_ADAPTER_ID = "maverick-hosted-tool-loop"
HOSTED_AGENTIC_ADAPTER_VERSION = "33"


def build_hosted_agentic_engine_adapter(
    state,
    *,
    provider_registry: ProviderRegistry,
    classifier: HostedContentClassifier | None = None,
) -> HostedAgenticEngineAdapter:
    """Compose the hosted loop from live Core-owned policy and storage surfaces."""
    if (
        state.runtime_tool_ledger is None
        or state.provider_private_state_service is None
        or state.agentic_egress_evaluator is None
    ):
        raise RuntimeError("Hosted agentic runtime dependencies are unavailable.")
    provider_runtimes = build_hosted_provider_runtime_registry()
    process_registry = HostedToolProcessRegistry(store=state.runtime_store)
    adapter_holder: dict[str, HostedAgenticEngineAdapter] = {}

    def policy_resolver(context):
        try:
            live = state.provider_store.get_workspace_agentic_profile_binding(
                context.binding.workspace_binding_id
            )
            if not live.enabled or live.workspace_id != context.binding.workspace_id:
                raise HostedAgenticLoopError("workspace_profile_binding_disabled")
            return intersect_runtime_policies(
                context.binding.profile_policy_ceiling_snapshot,
                context.binding.workspace_policy_ceiling_snapshot,
                live.workspace_policy_ceiling,
            )
        except HostedAgenticLoopError:
            raise
        except Exception as error:
            raise HostedAgenticLoopError("runtime_policy_unavailable") from error

    def authority_refresher(context):
        try:
            return resolve_runtime_authority_snapshot(
                state,
                session=context.session,
                adapter=adapter_holder["adapter"],
                turn_id=context.correlation_id,
                currently_authorized_tool_handles=authorized_core_tool_handles(context.binding),
            )
        except CapabilityCertificateError as error:
            raise HostedAgenticLoopError(error.reason_code) from error

    def authority_revalidator(context, authority):
        try:
            return revalidate_runtime_authority_snapshot(
                state,
                session=context.session,
                adapter=adapter_holder["adapter"],
                authority=authority,
            )
        except CapabilityCertificateError as error:
            raise HostedAgenticLoopError(error.reason_code) from error

    # Transient content is admitted only when the server-owned input composer
    # attaches an exact canonical classification.  The generic classifier is
    # deliberately fail-closed and cannot promote bytes based on provenance.
    content_classifier = classifier or classify_hosted_content_fail_closed

    def revalidate_content_classification(context, classification):
        workspace_id = str(
            getattr(getattr(context, "session", None), "workspace_id", "")
            or getattr(context, "workspace_id", "")
            or ""
        )
        return revalidate_hosted_content_classification(
            state.workspace_store,
            workspace_id=workspace_id,
            classification=classification,
        )

    def classify_resource(observation, provenance):
        authoritative = resource_classification_for_observation(
            state.workspace_store.get_resource_classification(
                workspace_id=observation.workspace_id,
                resource_kind=observation.resource_kind,
                resource_ref=observation.resource_ref,
            ),
            workspace_id=observation.workspace_id,
            resource_kind=observation.resource_kind,
            resource_ref=observation.resource_ref,
            resource_identity=observation.resource_identity,
            resource_revision=observation.resource_revision,
            resource_digest=observation.resource_digest,
            provenance=provenance,
        )
        return resolve_runtime_public_resource_classification(
            state.workspace_store,
            observation=observation,
            provenance=provenance,
            authoritative=authoritative,
        )

    loop = HostedAgenticLoop(
        provider_runtimes=provider_runtimes,
        request_builder=HostedAgenticRequestBuilder(
            egress_evaluator=state.agentic_egress_evaluator,
            classifier=content_classifier,
            attestation_resolver=state.workspace_store.get_data_attestation,
            semantic_compiler=HostedSemanticEnvelopeCompiler(
                classifier=content_classifier,
                platform_instruction=HOSTED_TOOL_USE_INSTRUCTION,
                resource_classification_resolver=classify_resource,
                classification_revalidator=revalidate_content_classification,
            ),
            classification_revalidator=revalidate_content_classification,
        ),
        tool_orchestrator_resolver=lambda context, actor: _tool_orchestrator(
            context,
            actor=actor,
            state=state,
            ledger=state.runtime_tool_ledger,
            workspace_store=state.workspace_store,
            process_registry=process_registry,
        ),
        tool_ledger=state.runtime_tool_ledger,
        private_state_service=state.provider_private_state_service,
        policy_resolver=policy_resolver,
        authority_refresher=authority_refresher,
        authority_revalidator=authority_revalidator,
        actor_context_resolver=lambda context: _actor_context(state, context),
        credential_resolver=lambda context: _credential(state, context),
        turn_status_callback=build_hosted_turn_status_callback(state.runtime_store),
    )
    adapter = HostedAgenticEngineAdapter(
        runtime_engine_id=HOSTED_AGENTIC_ENGINE_ID,
        adapter_id=HOSTED_AGENTIC_ADAPTER_ID,
        adapter_version=HOSTED_AGENTIC_ADAPTER_VERSION,
        loop=loop,
        composition_components=(
            build_hosted_agentic_engine_adapter,
            build_hosted_provider_runtime_registry,
            resolve_filesystem_mutation_lineage,
        ),
        process_registry=process_registry,
    )
    adapter_holder["adapter"] = adapter
    provider_registry.register_agentic_runtime_adapter(adapter)
    return adapter


def classify_hosted_content_fail_closed(
    _context,
    provenance: str,
    content: object,
) -> HostedContentClassification:
    """Fail closed; certified Core schemas bypass this generic classifier entirely."""
    trust = {
        "provider_state": "trusted_platform",
        "platform_instruction": "trusted_platform",
        "finalization_instruction": "trusted_platform",
        "tool_result": "untrusted_tool_output",
    }.get(provenance, "trusted_actor")
    try:
        content_digest = hashlib.sha256(canonical_egress_content(content)).hexdigest()
    except (TypeError, ValueError):
        content_digest = ""
    return HostedContentClassification(
        "unclassified",
        trust,
        content_digest=content_digest,
    )


def _tool_orchestrator(
    context,
    *,
    actor,
    state,
    ledger,
    workspace_store,
    process_registry,
) -> RuntimeToolOrchestrator:
    # Registry builders load app-hosting integration, which depends on the API
    # platform state.  Keep these imports on the post-bootstrap path to avoid a
    # platform_state -> hosted factory -> app registry initialization cycle.
    from core.cli.registry_builder import build_core_cli_registry
    from core.mcp.registry_builder import build_core_mcp_registry

    root = Path(context.session.workspace_root)
    cli_context = _cli_context(actor)
    mcp_context = _mcp_context(actor)
    common_registry_arguments = {
        "app_store": state.app_store,
        "identity_store": state.identity_store,
        "workspace_store": state.workspace_store,
        "provider_store": state.provider_store,
        "runtime_store": state.runtime_store,
        "inter_agent_store": state.inter_agent_store,
        "secret_store": state.secret_store,
        "recovery_store": state.recovery_store,
        "job_service": state.job_service,
        "provider_registry": state.provider_registry,
        "observability_store": state.observability_store,
        "runtime_event_bus": state.runtime_event_bus,
        "runtime_thread_event_bus": state.runtime_thread_event_bus,
        "app_event_bus": state.app_event_bus,
        "workspace_id": context.session.workspace_id,
        "start_path": state.repository_root,
    }
    cli_registry = build_core_cli_registry(
        **common_registry_arguments,
        context=cli_context,
        sidecar_browser_sessions=state.sidecar_browser_sessions,
    )
    mcp_registry = build_core_mcp_registry(
        **common_registry_arguments,
        context=mcp_context,
    )
    result_admission_resolver = build_hosted_tool_result_admission_resolver(
        cli_registry=cli_registry,
        mcp_registry=mcp_registry,
        public_content_authority_resolver=lambda workspace_id: (
            runtime_public_content_authority_for_workspace(
                workspace_store,
                workspace_id,
            )
        ),
    )
    result_preflight_resolver = build_hosted_tool_result_preflight_resolver(
        cli_registry=cli_registry,
        mcp_registry=mcp_registry,
        process_registry=process_registry,
        public_content_authority_resolver=lambda workspace_id: (
            runtime_public_content_authority_for_workspace(
                workspace_store,
                workspace_id,
            )
        ),
    )

    def classify_resource(observation, provenance):
        authoritative = resource_classification_for_observation(
            workspace_store.get_resource_classification(
                workspace_id=observation.workspace_id,
                resource_kind=observation.resource_kind,
                resource_ref=observation.resource_ref,
            ),
            workspace_id=observation.workspace_id,
            resource_kind=observation.resource_kind,
            resource_ref=observation.resource_ref,
            resource_identity=observation.resource_identity,
            resource_revision=observation.resource_revision,
            resource_digest=observation.resource_digest,
            provenance=provenance,
        )
        authoritative = resolve_runtime_public_resource_classification(
            workspace_store,
            observation=observation,
            provenance=provenance,
            authoritative=authoritative,
        )
        return resolve_filesystem_mutation_lineage(
            observation=observation,
            provenance=provenance,
            authoritative=authoritative,
            ledger=ledger,
            session_id=context.session.session_id,
            authority_store=workspace_store,
        )

    return RuntimeToolOrchestrator(
        catalog_builder=RuntimeToolCatalogBuilder(
            cli_registry=cli_registry,
            mcp_registry=mcp_registry,
            core_capabilities=build_core_runtime_tool_capabilities(
                workspace_id=context.session.workspace_id,
                workspace_root=root,
                runtime_root=Path(context.session.runtime_root),
                process_registry=process_registry,
                cli_registry=cli_registry,
                mcp_registry=mcp_registry,
                tool_ledger=ledger,
                result_classification_resolver=result_admission_resolver,
                resource_classification_resolver=classify_resource,
                attachment_read_fences=runtime_attachment_read_fences(
                    getattr(context, "input_sources", ())
                ),
            ),
            result_classification_resolver=result_admission_resolver,
            result_preflight_resolver=result_preflight_resolver,
        ),
        ledger=ledger,
        classification_authority_store=workspace_store,
    )


def _cli_context(actor: RuntimeToolActorContext) -> CliInvocationContext:
    return CliInvocationContext(
        caller_kind=(
            "full_access_agent"
            if actor.execution_mode == "full-access"
            else "sandbox_agent"
        ),
        workspace_id=actor.workspace_id,
        agent_id=actor.agent_id,
        effective_mode=actor.execution_mode,
        platform_role=actor.platform_role,
        user_id=actor.actor_id,
        workspace_role=actor.workspace_role,
        runtime_session_id=actor.session_id,
    )


def _mcp_context(actor: RuntimeToolActorContext) -> McpInvocationContext:
    return McpInvocationContext(
        caller_kind=(
            "full_access_agent"
            if actor.execution_mode == "full-access"
            else "sandbox_agent"
        ),
        workspace_id=actor.workspace_id,
        agent_id=actor.agent_id,
        effective_mode=actor.execution_mode,
        platform_role=actor.platform_role,
        user_id=actor.actor_id,
        workspace_role=actor.workspace_role,
        runtime_session_id=actor.session_id,
    )


def _actor_context(state, context) -> RuntimeToolActorContext:
    try:
        platform_role, user_id, workspace_role = resolve_runtime_actor_roles(
            state,
            user_id=context.session.owner_user_id,
            workspace_id=context.session.workspace_id,
        )
    except AuthorizationError as error:
        raise HostedAgenticLoopError(error.reason) from error
    return RuntimeToolActorContext(
        workspace_id=context.session.workspace_id,
        actor_id=user_id,
        agent_id=context.session.agent_id,
        platform_role=platform_role,
        workspace_role=workspace_role,
        session_id=context.session.session_id,
        execution_mode=context.effective_authority.execution_mode,
        consumer_app_id=context.session.source_app_id,
    )


def _credential(state, context) -> EphemeralCredential | None:
    binding_id = context.binding.credential_binding_id
    if not binding_id:
        return None
    try:
        binding = resolve_provider_binding(
            state.provider_store,
            binding_id=binding_id,
            provider_id=context.binding.model_provider_id,
            workspace_id=context.binding.workspace_id,
        )
        if binding is None:
            return None
        lease = resolve_secret_for_runtime(
            state.secret_store,
            context=SecretResolutionContext(
                workspace_id=context.binding.workspace_id,
                provider_id=context.binding.model_provider_id,
                runtime_session_id=context.session.session_id,
                allow_unbound_secret_refs=True,
                platform_delivery=True,
                action="provider.agentic.execute",
                target=context.binding.model_provider_id,
                actor_user_id=context.session.owner_user_id,
            ),
            secret_ref=binding.secret_ref,
            observability_store=state.observability_store,
        )
        return EphemeralCredential(lease.value)
    except ProviderError as error:
        raise HostedAgenticLoopError("credential_binding_unavailable") from error
    except Exception as error:
        raise HostedAgenticLoopError("credential_resolution_failed") from error
