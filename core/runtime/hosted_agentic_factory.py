"""Production composition for the Core-owned hosted agentic runtime."""

from __future__ import annotations

from pathlib import Path

from core.authorization.errors import AuthorizationError
from core.cli.command_registry import CliCommandRegistry
from core.mcp.tool_registry import McpToolRegistry
from core.providers.agentic_protocol import EphemeralCredential
from core.providers.errors import CapabilityCertificateError, ProviderError
from core.providers.google_interactions_client import (
    GoogleInteractionsAgenticClient,
    google_36_flash_request_ceiling_microusd,
)
from core.providers.google_interactions_models import (
    GOOGLE_INTERACTIONS_CODEC_ID,
    GOOGLE_INTERACTIONS_CODEC_VERSION,
    GOOGLE_INTERACTIONS_CONTENT_TYPE,
    GOOGLE_INTERACTIONS_SCHEMA_VERSION,
)
from core.providers.google_interactions_state import inspect_google_interaction_state
from core.providers.openrouter_agentic_client import (
    OpenRouterAgenticClient,
    openrouter_deepinfra_v4_flash_request_ceiling_microusd,
)
from core.providers.openrouter_agentic_models import (
    OPENROUTER_AGENTIC_CODEC_ID,
    OPENROUTER_AGENTIC_CODEC_VERSION,
    OPENROUTER_AGENTIC_CONTENT_TYPE,
    OPENROUTER_AGENTIC_SCHEMA_VERSION,
)
from core.providers.openrouter_agentic_state import inspect_openrouter_chat_state
from core.providers.provider_credentials import resolve_provider_binding
from core.providers.provider_registry import ProviderRegistry
from core.runtime.authority import (
    intersect_runtime_policies,
)
from core.runtime.authority_service import resolve_runtime_authority_snapshot
from core.runtime.hosted_agentic_engine import (
    HostedAgenticEngineAdapter,
    build_hosted_turn_status_callback,
)
from core.runtime.hosted_agentic_loop import HostedAgenticLoop
from core.runtime.hosted_agentic_models import (
    HostedAgenticLoopError,
    HostedContentClassification,
    HostedContentClassifier,
    HostedProviderPrivateCodec,
)
from core.runtime.hosted_agentic_request import HostedAgenticRequestBuilder
from core.runtime.hosted_agentic_policy import authorized_core_tool_handles
from core.runtime.hosted_provider_runtime import (
    HostedProviderRuntime,
    HostedProviderRuntimeRegistry,
)
from core.runtime.runtime_actor import resolve_runtime_actor_roles
from core.runtime.tool_catalog import RuntimeToolActorContext, RuntimeToolCatalogBuilder
from core.runtime.tool_core_capabilities import build_core_runtime_tool_capabilities
from core.runtime.tool_orchestrator import RuntimeToolOrchestrator
from core.workspaces.data_governance import resource_classification_for_observation
from core.secrets.models import SecretResolutionContext
from core.secrets.secret_resolution import resolve_secret_for_runtime


HOSTED_AGENTIC_ENGINE_ID = "maverick-tool-loop"
HOSTED_AGENTIC_ADAPTER_ID = "maverick-hosted-tool-loop"
HOSTED_AGENTIC_ADAPTER_VERSION = "7"


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
    provider_runtimes = _provider_runtimes()
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

    loop = HostedAgenticLoop(
        provider_runtimes=provider_runtimes,
        request_builder=HostedAgenticRequestBuilder(
            egress_evaluator=state.agentic_egress_evaluator,
            classifier=classifier or classify_hosted_content_fail_closed,
            attestation_resolver=state.workspace_store.get_data_attestation,
        ),
        tool_orchestrator_resolver=lambda context, _actor: _tool_orchestrator(
            context,
            ledger=state.runtime_tool_ledger,
            workspace_store=state.workspace_store,
        ),
        tool_ledger=state.runtime_tool_ledger,
        private_state_service=state.provider_private_state_service,
        policy_resolver=policy_resolver,
        authority_refresher=authority_refresher,
        actor_context_resolver=lambda context: _actor_context(state, context),
        credential_resolver=lambda context: _credential(state, context),
        turn_status_callback=build_hosted_turn_status_callback(state.runtime_store),
    )
    adapter = HostedAgenticEngineAdapter(
        runtime_engine_id=HOSTED_AGENTIC_ENGINE_ID,
        adapter_id=HOSTED_AGENTIC_ADAPTER_ID,
        adapter_version=HOSTED_AGENTIC_ADAPTER_VERSION,
        loop=loop,
    )
    adapter_holder["adapter"] = adapter
    provider_registry.register_agentic_runtime_adapter(adapter)
    return adapter


def classify_hosted_content_fail_closed(
    _context,
    provenance: str,
    _content: object,
) -> HostedContentClassification:
    """Fail closed; certified Core schemas bypass this generic classifier entirely."""
    trust = {
        "provider_state": "trusted_platform",
        "platform_instruction": "trusted_platform",
        "tool_result": "untrusted_tool_output",
    }.get(provenance, "trusted_actor")
    return HostedContentClassification("unclassified", trust)


def _provider_runtimes() -> HostedProviderRuntimeRegistry:
    registry = HostedProviderRuntimeRegistry()
    registry.register(
        HostedProviderRuntime(
            model_provider_id="google-ai-studio",
            provider_protocol="google-interactions",
            provider_api_version="v1",
            client=GoogleInteractionsAgenticClient(state_mode="stateful"),
            private_codec=HostedProviderPrivateCodec(
                codec_id=GOOGLE_INTERACTIONS_CODEC_ID,
                codec_version=GOOGLE_INTERACTIONS_CODEC_VERSION,
                schema_version=GOOGLE_INTERACTIONS_SCHEMA_VERSION,
                content_type=GOOGLE_INTERACTIONS_CONTENT_TYPE,
            ),
            cost_estimator=google_36_flash_request_ceiling_microusd,
            private_state_inspector=lambda content: inspect_google_interaction_state(
                content,
                mode="stateful",
            ),
        )
    )
    registry.register(
        HostedProviderRuntime(
            model_provider_id="openrouter",
            provider_protocol="openrouter-chat-completions",
            provider_api_version="v1",
            client=OpenRouterAgenticClient(),
            private_codec=HostedProviderPrivateCodec(
                codec_id=OPENROUTER_AGENTIC_CODEC_ID,
                codec_version=OPENROUTER_AGENTIC_CODEC_VERSION,
                schema_version=OPENROUTER_AGENTIC_SCHEMA_VERSION,
                content_type=OPENROUTER_AGENTIC_CONTENT_TYPE,
            ),
            cost_estimator=openrouter_deepinfra_v4_flash_request_ceiling_microusd,
            private_state_inspector=inspect_openrouter_chat_state,
        )
    )
    return registry


def _tool_orchestrator(context, *, ledger, workspace_store) -> RuntimeToolOrchestrator:
    root = Path(context.session.workspace_root)
    return RuntimeToolOrchestrator(
        catalog_builder=RuntimeToolCatalogBuilder(
            cli_registry=CliCommandRegistry(),
            mcp_registry=McpToolRegistry(),
            core_capabilities=build_core_runtime_tool_capabilities(
                workspace_id=context.session.workspace_id,
                workspace_root=root,
                resource_classification_resolver=lambda observation, provenance: (
                    resource_classification_for_observation(
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
                ),
            ),
        ),
        ledger=ledger,
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
