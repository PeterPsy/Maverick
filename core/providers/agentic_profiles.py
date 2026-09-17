"""Direct provider/model configuration for agentic runtime sessions."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib

from core.execution_policy.models import ExecutionMode
from core.providers.agentic_models import (
    AgenticProfileDefinition,
    WorkspaceAgenticProfileBinding,
    codex_routing_constraint,
    codex_runtime_capabilities,
    codex_runtime_policy,
    default_actor_selection_policy,
)
from core.providers.errors import (
    AgenticProfileError,
    ProviderCredentialBindingError,
    ProviderNotFoundError,
)
from core.providers.models import ProviderDefinition, ProviderSelection
from core.providers.provider_credentials import resolve_provider_binding
from core.providers.provider_registry import ProviderRegistry
from core.providers.store import ProviderStore
from core.runtime.agentic_feature_flags import (
    MAVERICK_FEATURE_AGENTIC_ADAPTER_CONTRACT,
    MAVERICK_FEATURE_AGENTIC_PROFILES,
    feature_enabled,
)
from core.runtime.authority import intersect_runtime_policies
from core.runtime.execution_binding import (
    RuntimeExecutionBinding,
    build_runtime_execution_binding,
)
from core.runtime.remote_agentic_admission import require_remote_agentic_session_admission


CODEX_ADAPTER_ID = "codex-app-server"
CODEX_ADAPTER_VERSION = "2"
DEFAULT_EGRESS_POLICY_ID = "local-runtime-no-remote-egress"
DEFAULT_EGRESS_POLICY_REVISION = "1"


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


def ensure_codex_workspace_profile(
    store: ProviderStore,
    *,
    definition: ProviderDefinition,
    selection: ProviderSelection,
    now: datetime | None = None,
) -> tuple[AgenticProfileDefinition, WorkspaceAgenticProfileBinding]:
    """Publish the current Codex model config and select it for a workspace."""
    if definition.provider_id != "codex" or definition.provider_role != "runtime_engine":
        raise AgenticProfileError("Codex model configuration requires the Codex runtime.")
    timestamp = now or utcnow()
    profile = publish_codex_agentic_profile(
        store,
        definition=definition,
        model_id=str(selection.model_id or definition.default_model_family or "").strip(),
        now=timestamp,
    )
    binding_id = _default_workspace_binding_id(selection.workspace_id)
    existing = next(
        (
            item
            for item in store.list_workspace_agentic_profile_bindings(selection.workspace_id)
            if item.binding_id == binding_id
        ),
        None,
    )
    binding = WorkspaceAgenticProfileBinding(
        binding_id=binding_id,
        workspace_id=selection.workspace_id,
        definition_id=profile.definition_id,
        credential_binding_id=selection.binding_id,
        enabled=True,
        is_default=True,
        actor_policy=(
            default_actor_selection_policy() if existing is None else existing.actor_policy
        ),
        workspace_policy_ceiling=(
            profile.policy_ceiling
            if existing is None
            else existing.workspace_policy_ceiling
        ),
        egress_policy_id=profile.egress_policy_id,
        egress_policy_revision=profile.egress_policy_revision,
        created_at=timestamp if existing is None else existing.created_at,
        updated_at=timestamp,
    )
    store.save_workspace_agentic_profile_binding(binding)
    return profile, binding


def publish_codex_agentic_profile(
    store: ProviderStore,
    *,
    definition: ProviderDefinition,
    model_id: str,
    now: datetime | None = None,
) -> AgenticProfileDefinition:
    """Upsert the current direct Codex model configuration."""
    if definition.provider_id != "codex" or definition.provider_role != "runtime_engine":
        raise AgenticProfileError("Codex model configuration requires the Codex runtime.")
    normalized_model_id = str(model_id or definition.default_model_family or "").strip()
    if not normalized_model_id:
        raise AgenticProfileError("Codex model configuration requires a model id.")
    profile = _codex_profile_definition(
        definition=definition,
        model_id=normalized_model_id,
        now=now or utcnow(),
    )
    from core.providers.native_agent_projection import codex_model_profile_projection

    profile = codex_model_profile_projection(store, profile, definition)
    return store.save_agentic_profile_definition(profile)


def resolve_workspace_agentic_profile(
    store: ProviderStore,
    *,
    workspace_id: str,
    binding_id: str | None = None,
    enforce_remote_admission: bool = True,
    workspace_store: object | None = None,
) -> tuple[AgenticProfileDefinition, WorkspaceAgenticProfileBinding]:
    """Resolve one direct, enabled workspace provider/model configuration."""
    if not feature_enabled(MAVERICK_FEATURE_AGENTIC_PROFILES):
        raise AgenticProfileError("agentic_profiles_disabled")
    bindings = store.list_workspace_agentic_profile_bindings(workspace_id)
    if binding_id:
        binding = next((item for item in bindings if item.binding_id == binding_id), None)
    else:
        defaults = [item for item in bindings if item.enabled and item.is_default]
        if len(defaults) > 1:
            raise AgenticProfileError("workspace_agentic_default_ambiguous")
        binding = defaults[0] if defaults else None
    if binding is None or not binding.enabled:
        raise AgenticProfileError("workspace_profile_binding_disabled")
    definition = store.get_agentic_profile_definition(binding.definition_id)
    if enforce_remote_admission:
        require_remote_agentic_session_admission(
            definition,
            workspace_id=workspace_id,
            workspace_store=workspace_store,
        )
    if binding.credential_binding_id:
        credential = resolve_provider_binding(
            store,
            provider_id=definition.model_provider_id,
            workspace_id=workspace_id,
            binding_id=binding.credential_binding_id,
        )
        if credential is None:
            raise ProviderCredentialBindingError("credential_binding_unavailable")
    return definition, binding


def build_pinned_execution_binding(
    store: ProviderStore,
    registry: ProviderRegistry,
    *,
    session_id: str,
    workspace_id: str,
    execution_mode: ExecutionMode,
    workspace_binding_id: str | None = None,
    reasoning_effort: str | None = None,
    now: datetime | None = None,
    workspace_store: object | None = None,
) -> RuntimeExecutionBinding:
    """Resolve direct workspace settings into the small session binding."""
    if not feature_enabled(MAVERICK_FEATURE_AGENTIC_ADAPTER_CONTRACT):
        raise AgenticProfileError("agentic_adapter_contract_disabled")
    definition, binding = resolve_workspace_agentic_profile(
        store,
        workspace_id=workspace_id,
        binding_id=workspace_binding_id,
        workspace_store=workspace_store,
    )
    try:
        model_provider = registry.get_provider_definition(definition.model_provider_id)
    except ProviderNotFoundError:
        model_provider = registry.get_provider_definition(definition.runtime_engine_id)
    if model_provider.requires_credentials and not binding.credential_binding_id:
        raise ProviderCredentialBindingError("credential_binding_unavailable")
    provider = registry.get_provider_definition(definition.runtime_engine_id)
    adapter = registry.get_agentic_runtime_adapter(provider.provider_id)
    adapter_version = str(getattr(adapter, "adapter_version", ""))
    if definition.adapter_version_constraint != f"=={adapter_version}":
        raise AgenticProfileError("adapter_version_mismatch")
    from core.providers.execution_family_readiness import inspect_agentic_family_readiness

    readiness = inspect_agentic_family_readiness(
        definition=definition,
        binding=binding,
        registry=registry,
        store=store,
    )
    if not readiness.complete:
        raise AgenticProfileError(readiness.reason_code or "agentic_runtime_unavailable")
    selected_reasoning = _validated_reasoning_effort(
        definition,
        reasoning_effort=reasoning_effort,
    )
    return build_runtime_execution_binding(
        session_id=session_id,
        workspace_id=workspace_id,
        workspace_binding_id=binding.binding_id,
        runtime_engine_id=definition.runtime_engine_id,
        adapter_id=definition.adapter_id,
        adapter_version=adapter_version,
        model_provider_id=definition.model_provider_id,
        model_id=definition.model_id,
        model_revision=definition.model_revision,
        model_revision_policy=definition.model_revision_policy,
        provider_protocol=definition.provider_protocol,
        provider_api_version=definition.provider_api_version,
        routing_constraint=definition.routing_constraint,
        credential_binding_id=binding.credential_binding_id,
        reasoning_effort=selected_reasoning,
        reasoning_efforts=definition.reasoning_efforts,
        capabilities=definition.capabilities,
        execution_mode=execution_mode,
        runtime_policy=intersect_runtime_policies(
            definition.policy_ceiling,
            binding.workspace_policy_ceiling,
        ),
        egress_policy_id=binding.egress_policy_id,
        egress_policy_revision=binding.egress_policy_revision,
        created_at=now or utcnow(),
        context_policy=definition.context_policy,
    )


def _validated_reasoning_effort(
    definition: AgenticProfileDefinition,
    *,
    reasoning_effort: str | None,
) -> str | None:
    normalized = (
        str(reasoning_effort or "").strip()
        or definition.default_reasoning_effort
        or None
    )
    if normalized is not None and normalized not in definition.reasoning_efforts:
        raise AgenticProfileError("profile_reasoning_effort_unsupported")
    return normalized


def provider_selection_from_execution_binding(
    binding: RuntimeExecutionBinding,
) -> ProviderSelection:
    """Project concrete session settings into the provider launch input."""
    return ProviderSelection(
        selection_id=f"session:{binding.session_id}:{binding.execution_binding_id}",
        workspace_id=binding.workspace_id,
        provider_id=binding.runtime_engine_id,
        binding_id=binding.credential_binding_id,
        selection_scope="workspace_default",
        selection_reason="runtime session configuration",
        created_at=binding.created_at,
        updated_at=binding.created_at,
        model_id=binding.model_id,
        model_reasoning_effort=binding.reasoning_effort,
    )


def _codex_profile_definition(
    *,
    definition: ProviderDefinition,
    model_id: str,
    now: datetime,
) -> AgenticProfileDefinition:
    identity = hashlib.sha256(f"codex\0{model_id}".encode()).hexdigest()[:16]
    return AgenticProfileDefinition(
        definition_id=f"agentic-profile-codex-{identity}",
        display_name=f"Codex · {model_id}",
        runtime_engine_id="codex",
        model_provider_id="codex",
        model_id=model_id,
        provider_protocol="codex-app-server-stdio",
        provider_api_version=None,
        adapter_id=CODEX_ADAPTER_ID,
        adapter_version_constraint=f"=={CODEX_ADAPTER_VERSION}",
        routing_constraint=codex_routing_constraint(),
        policy_ceiling=codex_runtime_policy(),
        capabilities=codex_runtime_capabilities(),
        reasoning_efforts=tuple(
            item.effort
            for option in definition.model_options
            if option.model_id == model_id
            for item in option.supported_reasoning_efforts
        ),
        default_reasoning_effort=next(
            (
                option.default_reasoning_effort
                for option in definition.model_options
                if option.model_id == model_id
            ),
            None,
        ),
        created_at=now,
        egress_policy_id=DEFAULT_EGRESS_POLICY_ID,
        egress_policy_revision=DEFAULT_EGRESS_POLICY_REVISION,
    )


def _default_workspace_binding_id(workspace_id: str) -> str:
    digest = hashlib.sha256(workspace_id.encode("utf-8")).hexdigest()[:16]
    return f"workspace-agentic-default-{digest}"
