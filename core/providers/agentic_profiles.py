"""Profile publication, workspace binding, and pinned resolution services."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import hashlib

from core.execution_policy.models import ExecutionMode
from core.providers.agentic_models import (
    AgenticProfileDefinition,
    AgenticProfileDefinitionStatus,
    WorkspaceAgenticProfileBinding,
    codex_routing_constraint,
    codex_runtime_policy,
    default_actor_selection_policy,
)
from core.providers.errors import (
    AgenticProfileError,
    CapabilityCertificateError,
    ProviderCredentialBindingError,
    ProviderNotFoundError,
)
from core.providers.certificate_service import (
    runtime_adapter_artifact_digest,
    validate_certificate_for_binding,
)
from core.providers.models import ProviderDefinition, ProviderSelection
from core.providers.provider_credentials import resolve_provider_binding
from core.providers.provider_registry import ProviderRegistry
from core.providers.store import ProviderStore
from core.runtime.execution_binding import RuntimeExecutionBinding, build_runtime_execution_binding
from core.runtime.agentic_feature_flags import (
    MAVERICK_FEATURE_AGENTIC_ADAPTER_CONTRACT,
    MAVERICK_FEATURE_AGENTIC_PROFILES,
    feature_enabled,
)


CODEX_PROFILE_REVISION = "6"
CODEX_PREVIOUS_PROFILE_REVISIONS = ("1", "2", "3", "4", "5")
CODEX_ADAPTER_ID = "codex-app-server"
CODEX_ADAPTER_VERSION = "2"
CAPABILITY_CERTIFICATE_PREFIX = "capability-certificate"
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
    """Publish the exact Codex model profile and bind the workspace default."""
    if definition.provider_id != "codex" or definition.provider_role != "runtime_engine":
        raise AgenticProfileError("Phase-0 agentic profile publication supports the Codex runtime only.")
    model_id = str(selection.model_id or definition.default_model_family or "").strip()
    timestamp = now or utcnow()
    profile = publish_codex_agentic_profile(
        store,
        definition=definition,
        model_id=model_id,
        now=timestamp,
    )

    binding_id = _default_workspace_binding_id(selection.workspace_id)
    bindings = store.list_workspace_agentic_profile_bindings(selection.workspace_id)
    existing = next((item for item in bindings if item.binding_id == binding_id), None)
    if existing is None:
        binding = WorkspaceAgenticProfileBinding(
            binding_id=binding_id,
            workspace_id=selection.workspace_id,
            definition_id=profile.definition_id,
            definition_revision=profile.revision,
            credential_binding_id=selection.binding_id,
            enabled=True,
            is_default=True,
            actor_policy=default_actor_selection_policy(),
            workspace_policy_ceiling=profile.policy_ceiling,
            egress_policy_id=DEFAULT_EGRESS_POLICY_ID,
            egress_policy_revision=DEFAULT_EGRESS_POLICY_REVISION,
            revision=0,
            created_at=timestamp,
            updated_at=timestamp,
        )
        store.save_workspace_agentic_profile_binding(binding, expected_revision=None)
        return profile, binding
    desired = replace(
        existing,
        definition_id=profile.definition_id,
        definition_revision=profile.revision,
        credential_binding_id=selection.binding_id,
        enabled=True,
        is_default=True,
    )
    if desired == existing:
        return profile, existing
    binding = replace(desired, revision=existing.revision + 1, updated_at=timestamp)
    store.save_workspace_agentic_profile_binding(binding, expected_revision=existing.revision)
    return profile, binding


def publish_codex_agentic_profile(
    store: ProviderStore,
    *,
    definition: ProviderDefinition,
    model_id: str,
    now: datetime | None = None,
) -> AgenticProfileDefinition:
    """Publish one immutable Codex definition without mutating workspace state."""
    if definition.provider_id != "codex" or definition.provider_role != "runtime_engine":
        raise AgenticProfileError("Codex profile publication requires the Codex runtime engine.")
    normalized_model_id = str(model_id or definition.default_model_family or "").strip()
    if not normalized_model_id:
        raise AgenticProfileError("Codex agentic profiles require an exact model id.")
    timestamp = now or utcnow()
    profile = _codex_profile_definition(
        definition=definition,
        model_id=normalized_model_id,
        now=timestamp,
    )
    try:
        profile = store.get_agentic_profile_definition(profile.definition_id, profile.revision)
    except ProviderNotFoundError:
        store.save_agentic_profile_definition(profile)
    status = store.get_agentic_profile_definition_status(profile.definition_id, profile.revision)
    if status is None:
        store.save_agentic_profile_definition_status(
            AgenticProfileDefinitionStatus(
                definition_id=profile.definition_id,
                definition_revision=profile.revision,
                rollout_status="preview",
                revision=0,
                updated_at=timestamp,
            ),
            expected_revision=None,
        )
    _suspend_previous_codex_revisions(store, definition_id=profile.definition_id, now=timestamp)
    return profile


def _suspend_previous_codex_revisions(
    store: ProviderStore,
    *,
    definition_id: str,
    now: datetime,
) -> None:
    """Suspend preview definitions certified against earlier adapter bytes."""
    for revision in CODEX_PREVIOUS_PROFILE_REVISIONS:
        status = store.get_agentic_profile_definition_status(
            definition_id,
            revision,
        )
        if status is None or status.rollout_status in {"disabled", "suspended"}:
            continue
        store.save_agentic_profile_definition_status(
            replace(
                status,
                rollout_status="suspended",
                revision=status.revision + 1,
                updated_at=now,
            ),
            expected_revision=status.revision,
        )


def resolve_workspace_agentic_profile(
    store: ProviderStore,
    *,
    workspace_id: str,
    binding_id: str | None = None,
) -> tuple[AgenticProfileDefinition, WorkspaceAgenticProfileBinding]:
    """Resolve one enabled workspace binding and its exact immutable definition."""
    if not feature_enabled(MAVERICK_FEATURE_AGENTIC_PROFILES):
        raise AgenticProfileError("agentic_profiles_disabled")
    bindings = store.list_workspace_agentic_profile_bindings(workspace_id)
    if binding_id:
        binding = next((item for item in bindings if item.binding_id == binding_id), None)
    else:
        defaults = [item for item in bindings if item.enabled and item.is_default]
        if len(defaults) > 1:
            raise AgenticProfileError("Workspace has multiple default agentic profile bindings.")
        binding = defaults[0] if defaults else None
    if binding is None or not binding.enabled:
        raise AgenticProfileError("workspace_profile_binding_disabled")
    definition = store.get_agentic_profile_definition(
        binding.definition_id,
        binding.definition_revision,
    )
    status = store.get_agentic_profile_definition_status(definition.definition_id, definition.revision)
    if status is None or status.rollout_status in {"disabled", "suspended"}:
        raise AgenticProfileError("profile_definition_invalid")
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
    legacy_inferred: bool = False,
    now: datetime | None = None,
) -> RuntimeExecutionBinding:
    """Resolve a workspace profile once and return its immutable session snapshot."""
    if not feature_enabled(MAVERICK_FEATURE_AGENTIC_ADAPTER_CONTRACT):
        raise AgenticProfileError("agentic_adapter_contract_disabled")
    timestamp = now or utcnow()
    definition, binding = resolve_workspace_agentic_profile(
        store,
        workspace_id=workspace_id,
        binding_id=workspace_binding_id,
    )
    model_provider = registry.get_provider_definition(definition.model_provider_id)
    if model_provider.requires_credentials and not binding.credential_binding_id:
        raise ProviderCredentialBindingError("credential_binding_unavailable")
    provider = registry.get_provider_definition(definition.runtime_engine_id)
    adapter = registry.get_agentic_runtime_adapter(provider.provider_id)
    adapter_version = str(getattr(adapter, "adapter_version", ""))
    if definition.adapter_version_constraint != f"=={adapter_version}":
        raise AgenticProfileError("adapter_version_mismatch")
    try:
        certificate = store.get_capability_certificate(definition.capability_certificate_id)
    except ProviderNotFoundError as error:
        raise CapabilityCertificateError("certificate_missing") from error
    normalized_reasoning_effort = _validated_reasoning_effort(
        certificate,
        reasoning_effort=reasoning_effort,
    )
    selection = _selection_projection(
        definition,
        binding,
        reasoning_effort=normalized_reasoning_effort,
        now=timestamp,
    )
    runtime_binding = build_runtime_execution_binding(
        session_id=session_id,
        workspace_id=workspace_id,
        profile_definition_id=definition.definition_id,
        profile_definition_revision=definition.revision,
        workspace_binding_id=binding.binding_id,
        workspace_binding_revision=binding.revision,
        capability_certificate_id=definition.capability_certificate_id,
        runtime_engine_id=definition.runtime_engine_id,
        adapter_id=definition.adapter_id,
        adapter_version=adapter_version,
        adapter_artifact_digest=runtime_adapter_artifact_digest(adapter),
        model_provider_id=definition.model_provider_id,
        model_id=definition.model_id,
        provider_protocol=definition.provider_protocol,
        provider_api_version=definition.provider_api_version,
        routing_constraint=definition.routing_constraint,
        credential_binding_id=binding.credential_binding_id,
        reasoning_effort=selection.model_reasoning_effort,
        certified_reasoning_efforts=certificate.certified_reasoning_efforts,
        default_reasoning_effort=certificate.default_reasoning_effort,
        execution_mode=execution_mode,
        profile_policy_ceiling=definition.policy_ceiling,
        workspace_policy_ceiling=binding.workspace_policy_ceiling,
        egress_policy_id=binding.egress_policy_id,
        egress_policy_revision=binding.egress_policy_revision,
        created_at=timestamp,
        certificate_evidence_digest=certificate.evidence_digest,
        legacy_inferred=legacy_inferred,
    )
    validate_certificate_for_binding(
        store,
        binding=runtime_binding,
        adapter=adapter,
        now=timestamp,
    )
    return runtime_binding


def _validated_reasoning_effort(
    certificate,
    *,
    reasoning_effort: str | None,
) -> str | None:
    normalized = (
        str(reasoning_effort or "").strip()
        or certificate.default_reasoning_effort
        or None
    )
    if normalized is None:
        return None
    if normalized not in certificate.certified_reasoning_efforts:
        raise AgenticProfileError("profile_reasoning_effort_unsupported")
    return normalized


def provider_selection_from_execution_binding(
    binding: RuntimeExecutionBinding,
) -> ProviderSelection:
    """Project pinned session fields into the legacy launch adapter input."""
    return ProviderSelection(
        selection_id=f"session:{binding.session_id}:{binding.execution_binding_id}",
        workspace_id=binding.workspace_id,
        provider_id=binding.runtime_engine_id,
        binding_id=binding.credential_binding_id,
        selection_scope="workspace_default",
        selection_reason="immutable runtime execution binding",
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
    identity = hashlib.sha256(
        f"codex\0{model_id}\0codex-app-server-v{CODEX_ADAPTER_VERSION}".encode()
    ).hexdigest()[:16]
    definition_id = f"agentic-profile-codex-{identity}"
    return AgenticProfileDefinition(
        definition_id=definition_id,
        revision=CODEX_PROFILE_REVISION,
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
        capability_certificate_id=f"{CAPABILITY_CERTIFICATE_PREFIX}:{definition_id}:{CODEX_PROFILE_REVISION}",
        created_at=now,
        egress_policy_id=DEFAULT_EGRESS_POLICY_ID,
        egress_policy_revision=DEFAULT_EGRESS_POLICY_REVISION,
    )


def _default_workspace_binding_id(workspace_id: str) -> str:
    digest = hashlib.sha256(workspace_id.encode("utf-8")).hexdigest()[:16]
    return f"workspace-agentic-default-{digest}"


def _selection_projection(
    definition: AgenticProfileDefinition,
    binding: WorkspaceAgenticProfileBinding,
    *,
    reasoning_effort: str | None,
    now: datetime,
) -> ProviderSelection:
    return ProviderSelection(
        selection_id=f"binding:{binding.binding_id}:{binding.revision}",
        workspace_id=binding.workspace_id,
        provider_id=definition.runtime_engine_id,
        binding_id=binding.credential_binding_id,
        selection_scope="workspace_default",
        selection_reason="workspace agentic profile binding",
        created_at=binding.created_at,
        updated_at=now,
        model_id=definition.model_id,
        model_reasoning_effort=reasoning_effort,
    )
