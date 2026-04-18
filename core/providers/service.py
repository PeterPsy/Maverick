"""Provider-domain service facade and builtin provider bootstrap."""

from __future__ import annotations

from datetime import UTC, datetime

from core.observability.service import record_platform_audit, record_platform_event
from core.providers.models import ProviderDefinition, ProviderSelection, RuntimeBackendLaunchSpec
from core.providers.provider_codex import CodexProviderAdapter
from core.providers.provider_credentials import resolve_provider_binding
from core.providers.provider_credentials import bind_provider_credential, disable_provider_binding
from core.providers.provider_registry import ProviderRegistry
from core.providers.provider_selection import ProviderSelectionService
from core.providers.store import ProviderStore
from core.runtime.runtime_session import RuntimeSessionRecord
from core.secrets.errors import SecretBindingError
from core.secrets.models import SecretResolutionContext
from core.secrets.secret_resolution import resolve_secret_for_runtime
from core.secrets.store import SecretStore
from core.skills.models import SkillDefinition, SkillMaterialization


def utcnow() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(tz=UTC)


def builtin_provider_registry(*, codex_command: str = "codex") -> ProviderRegistry:
    """Build the builtin provider registry shipped by the core."""
    registry = ProviderRegistry()
    registry.register_runtime_adapter(CodexProviderAdapter(codex_command=codex_command))
    return registry


def register_builtin_providers(
    store: ProviderStore,
    *,
    registry: ProviderRegistry | None = None,
    codex_command: str = "codex",
) -> list[ProviderDefinition]:
    """Persist builtin provider definitions into the provider store."""
    active_registry = registry or builtin_provider_registry(codex_command=codex_command)
    definitions = active_registry.list_provider_definitions()
    for definition in definitions:
        store.save_provider_definition(definition)
    return definitions


def list_available_providers(
    store: ProviderStore,
    *,
    registry: ProviderRegistry | None = None,
    codex_command: str = "codex",
) -> list[ProviderDefinition]:
    """List provider definitions from the authoritative registry."""
    active_registry = registry or builtin_provider_registry(codex_command=codex_command)
    register_builtin_providers(store, registry=active_registry, codex_command=codex_command)
    return active_registry.list_provider_definitions()


def configure_workspace_provider(
    store: ProviderStore,
    *,
    workspace_id: str,
    provider_id: str,
    binding_id: str | None = None,
    selection_reason: str = "configured by control-plane policy",
    registry: ProviderRegistry | None = None,
    codex_command: str = "codex",
    observability_store=None,
    now: datetime | None = None,
) -> ProviderSelection:
    """Persist the selected runtime provider for one workspace."""
    active_registry = registry or builtin_provider_registry(codex_command=codex_command)
    register_builtin_providers(store, registry=active_registry, codex_command=codex_command)
    service = ProviderSelectionService(store, active_registry)
    selection = service.configure_workspace_provider(
        workspace_id=workspace_id,
        provider_id=provider_id,
        binding_id=binding_id,
        selection_reason=selection_reason,
        now=now,
    )
    if observability_store is not None:
        record_platform_audit(
            observability_store,
            action="provider.selection.configure",
            status="succeeded",
            source_domain="providers",
            detail=f"Configured provider `{provider_id}` for workspace `{workspace_id}`.",
            workspace_id=workspace_id,
            provider_id=provider_id,
            payload={"workspace_id": workspace_id, "provider_id": provider_id, "binding_id": selection.binding_id},
        )
        record_platform_event(
            observability_store,
            event_type="provider.selection.configured",
            event_plane="platform",
            source_domain="providers",
            workspace_id=workspace_id,
            provider_id=provider_id,
            payload={"workspace_id": workspace_id, "provider_id": provider_id, "binding_id": selection.binding_id},
        )
    return selection


def resolve_provider_for_runtime_session(
    store: ProviderStore,
    *,
    session: RuntimeSessionRecord,
    registry: ProviderRegistry | None = None,
    codex_command: str = "codex",
) -> tuple[ProviderDefinition, ProviderSelection | None]:
    """Resolve the effective provider selection for one runtime session."""
    active_registry = registry or builtin_provider_registry(codex_command=codex_command)
    register_builtin_providers(store, registry=active_registry, codex_command=codex_command)
    service = ProviderSelectionService(store, active_registry)
    return service.resolve_runtime_backend_provider(workspace_id=session.workspace_id)


def build_runtime_backend_launch_spec(
    store: ProviderStore,
    *,
    session: RuntimeSessionRecord,
    registry: ProviderRegistry | None = None,
    codex_command: str = "codex",
    secret_store: SecretStore | None = None,
    observability_store=None,
) -> RuntimeBackendLaunchSpec:
    """Build the launch spec for the selected provider for one runtime session."""
    active_registry = registry or builtin_provider_registry(codex_command=codex_command)
    definition, selection = resolve_provider_for_runtime_session(
        store,
        session=session,
        registry=active_registry,
        codex_command=codex_command,
    )
    adapter = active_registry.get_runtime_adapter(definition.provider_id)
    secret_env: dict[str, str] = {}
    resolved_secret_refs: list[str] = []
    credential_binding_id: str | None = None
    if definition.requires_credentials:
        if secret_store is None:
            raise SecretBindingError(
                f"Provider `{definition.provider_id}` requires credentials but no secret store was provided for launch."
            )
        binding = resolve_provider_binding(
            store,
            provider_id=definition.provider_id,
            workspace_id=session.workspace_id,
            binding_id=None if selection is None else selection.binding_id,
        )
        if binding is None:
            raise SecretBindingError(f"Provider `{definition.provider_id}` has no active credential binding for runtime launch.")
        lease = resolve_secret_for_runtime(
            secret_store,
            context=SecretResolutionContext(
                workspace_id=session.workspace_id,
                provider_id=definition.provider_id,
                runtime_session_id=session.session_id,
                platform_delivery=True,
                allow_unbound_secret_refs=True,
            ),
            secret_ref=binding.secret_ref,
        )
        credential_binding_id = binding.binding_id
        resolved_secret_refs.append(lease.secret_ref)
        secret_env["MAVERICK_PROVIDER_SECRET"] = lease.value
    spec = adapter.build_launch_spec(
        session,
        secret_env=secret_env,
        credential_binding_id=credential_binding_id,
        resolved_secret_refs=resolved_secret_refs,
    )
    if observability_store is not None:
        record_platform_audit(
            observability_store,
            action="provider.launch_spec.build",
            status="succeeded",
            source_domain="providers",
            detail=f"Built runtime launch spec for provider `{definition.provider_id}`.",
            workspace_id=session.workspace_id,
            runtime_session_id=session.session_id,
            provider_id=definition.provider_id,
            payload={
                "provider_id": definition.provider_id,
                "execution_mode": spec.execution_mode,
                "credential_binding_id": credential_binding_id,
                "resolved_secret_refs": resolved_secret_refs,
            },
        )
        record_platform_event(
            observability_store,
            event_type="provider.launch_spec.built",
            event_plane="runtime",
            source_domain="providers",
            workspace_id=session.workspace_id,
            runtime_session_id=session.session_id,
            provider_id=definition.provider_id,
            payload={
                "provider_id": definition.provider_id,
                "execution_mode": spec.execution_mode,
                "credential_binding_id": credential_binding_id,
                "resolved_secret_refs": resolved_secret_refs,
            },
        )
    return spec


def prepare_runtime_skills(
    store: ProviderStore,
    *,
    session: RuntimeSessionRecord,
    skills: list[SkillDefinition],
    registry: ProviderRegistry | None = None,
    codex_command: str = "codex",
) -> list[SkillMaterialization]:
    """Prepare provider-specific runtime skill installation for one runtime session."""
    active_registry = registry or builtin_provider_registry(codex_command=codex_command)
    definition, _selection = resolve_provider_for_runtime_session(
        store,
        session=session,
        registry=active_registry,
        codex_command=codex_command,
    )
    adapter = active_registry.get_runtime_adapter(definition.provider_id)
    return adapter.prepare_runtime_skills(session, skills)


__all__ = [
    "bind_provider_credential",
    "builtin_provider_registry",
    "build_runtime_backend_launch_spec",
    "configure_workspace_provider",
    "disable_provider_binding",
    "list_available_providers",
    "prepare_runtime_skills",
    "register_builtin_providers",
    "resolve_provider_for_runtime_session",
    "utcnow",
]
