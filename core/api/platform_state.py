"""Runtime bootstrap state for the minimal hosted Maverick platform."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
import os
from pathlib import Path
import shutil
from typing import TYPE_CHECKING

from core.api.app_events import AppEventBus
from core.api.application import create_application
from core.api.control_store import ControlPlaneCollections, ControlStoreSettings
from core.api.persistence_cleanup_worker import run_pending_cleanup_plans
from core.egress.agentic_policy import AgenticEgressEvaluator
from core.apps.store import AppDocumentStore
from core.apps.runtime_root_capabilities import RuntimeRootCapabilityStore
from core.apps.sidecar_browser_sessions import SidecarBrowserSessionStore
from core.identity.service import bootstrap_default_admin
from core.identity.store import IdentityDocumentStore
from core.inter_agent.store import InterAgentDocumentStore
from core.jobs.events import JobEventBus
from core.jobs.service import JobService
from core.observability.store import ObservabilityDocumentStore
from core.providers.provider_codex import refresh_workspace_maverick_wrappers
from core.providers.agentic_migration import migrate_agentic_runtime_schema
from core.providers.provider_registry import ProviderRegistry
from core.providers.service import effective_provider_registry
from core.recovery.backend_restart import recover_interrupted_runtime_turns_after_backend_restart
from core.providers.store import ProviderDocumentStore
from core.recovery.store import RecoveryDocumentStore
from core.runtime.app_reference_classification import RuntimeAppReferenceClassificationResolver
from core.runtime.event_bus import RuntimeEventBus
from core.runtime.hosted_agentic_factory import build_hosted_agentic_engine_adapter
from core.runtime.hosted_runtime_registry_builder import (
    build_builtin_maverick_agent_onboarding_catalog,
)
from core.runtime.thread_event_bus import RuntimeThreadEventBus
from core.runtime.store import RuntimeDocumentStore
from core.runtime.provider_private_state import ProviderPrivateStateService
from core.runtime.provider_input_context import (
    RuntimeProviderInputClassificationResolver,
)
from core.runtime.tool_ledger import RuntimeToolLedger
from core.secrets.bootstrap import resolve_bootstrap_secret
from core.secrets.key_material import load_secret_store_key, load_secret_store_keyring
from core.secrets.store import SecretDocumentStore
from core.shared.repository import discover_repository_root
from core.usage.store import UsageDocumentStore
from core.workspaces.store import WorkspaceDocumentStore

if TYPE_CHECKING:
    from core.providers.maverick_agent_onboarding import MaverickAgentOnboardingCatalog


@dataclass(frozen=True)
class PlatformState:
    """Group the control-plane stores used by the local hosted platform."""

    repository_root: Path
    control_store_settings: ControlStoreSettings
    control_plane_collections: ControlPlaneCollections
    workspace_store: WorkspaceDocumentStore
    identity_store: IdentityDocumentStore
    app_store: AppDocumentStore
    provider_store: ProviderDocumentStore
    provider_registry: ProviderRegistry
    runtime_store: RuntimeDocumentStore
    inter_agent_store: InterAgentDocumentStore
    job_service: JobService
    job_event_bus: JobEventBus
    runtime_event_bus: RuntimeEventBus
    runtime_thread_event_bus: RuntimeThreadEventBus
    app_event_bus: AppEventBus
    secret_store: SecretDocumentStore
    recovery_store: RecoveryDocumentStore
    observability_store: ObservabilityDocumentStore
    usage_store: UsageDocumentStore
    sidecar_browser_sessions: SidecarBrowserSessionStore
    runtime_root_capabilities: RuntimeRootCapabilityStore
    root_shell_app_id: str
    lab_runtime_authorization: object | None = None
    runtime_tool_ledger: RuntimeToolLedger | None = None
    provider_private_state_service: ProviderPrivateStateService | None = None
    agentic_egress_evaluator: AgenticEgressEvaluator | None = None
    runtime_input_classification_resolver: (
        RuntimeProviderInputClassificationResolver | None
    ) = None
    runtime_app_reference_classification_resolver: (
        RuntimeAppReferenceClassificationResolver | None
    ) = None
    maverick_agent_onboarding_catalog: (
        MaverickAgentOnboardingCatalog | None
    ) = None


def bootstrap_platform_state(
    *,
    start_path: Path | None = None,
    now: datetime | None = None,
    recover_backend_restart: bool = False,
    install_builtin_apps: bool = True,
    register_builtin_provider_definitions: bool = True,
    bootstrap_admin: bool = True,
    runtime_input_classification_resolver: (
        RuntimeProviderInputClassificationResolver | None
    ) = None,
    runtime_app_reference_classification_resolver: (
        RuntimeAppReferenceClassificationResolver | None
    ) = None,
) -> PlatformState:
    """Build in-memory platform state and optionally run host bootstrap work."""
    repository_root = discover_repository_root(start_path=start_path)
    _remove_legacy_shared_provider_homes(repository_root)
    refresh_workspace_maverick_wrappers(repository_root)
    control_settings = ControlStoreSettings.from_environment(repository_root=repository_root)
    run_pending_cleanup_plans(repository_root=repository_root, active_settings=control_settings)
    from core.api.platform_store_composition import compose_platform_store_state

    state = compose_platform_store_state(
        repository_root=repository_root, control_settings=control_settings,
        key_loader=load_secret_store_key, keyring_loader=load_secret_store_keyring,
        root_shell_app_id=os.environ.get("MAVERICK_ROOT_SHELL_APP_ID", "base-shell").strip() or "base-shell",
        now=now, runtime_input_classification_resolver=runtime_input_classification_resolver,
        runtime_app_reference_classification_resolver=runtime_app_reference_classification_resolver,
    )
    workspace_store, identity_store, app_store = state.workspace_store, state.identity_store, state.app_store
    provider_store, provider_registry, runtime_store = state.provider_store, state.provider_registry, state.runtime_store
    job_service = state.job_service
    create_application(
        start_path=repository_root,
        workspace_store=workspace_store,
        app_store=app_store,
        provider_store=provider_store,
        provider_registry=provider_registry,
        install_builtin_apps=install_builtin_apps,
        register_providers=register_builtin_provider_definitions,
        now=now,
    )
    provider_registry = effective_provider_registry(
        provider_store,
        registry=provider_registry,
    )
    migrate_agentic_runtime_schema(
        provider_store,
        runtime_store,
        provider_registry,
        now=now,
    )
    if bootstrap_admin:
        admin_username, admin_password = _bootstrap_admin_credentials()
        bootstrap_default_admin(
            identity_store,
            workspace_store,
            username=admin_username,
            password=admin_password,
            now=now,
        )
    onboarding_now = now or datetime.now(tz=UTC)
    onboarding_catalog = build_builtin_maverick_agent_onboarding_catalog(
        now=onboarding_now,
    )
    state = replace(state, provider_registry=provider_registry, maverick_agent_onboarding_catalog=onboarding_catalog)
    hosted_adapter = build_hosted_agentic_engine_adapter(
        state,
        provider_registry=provider_registry,
        onboarding_catalog=onboarding_catalog,
    )
    if register_builtin_provider_definitions:
        onboarding_catalog.validate_runtime_adapter(hosted_adapter)
        onboarding_catalog.publish_profiles(provider_store, now=onboarding_now)
    if recover_backend_restart:
        recover_interrupted_runtime_turns_after_backend_restart(state)
        job_service.recover_expired_jobs()
    return state


def _bootstrap_admin_credentials() -> tuple[str, str | None]:
    username = os.environ.get("MAVERICK_ADMIN_USERNAME", "").strip()
    password_ref = os.environ.get("MAVERICK_ADMIN_PASSWORD_REF", "").strip()
    password = os.environ.get("MAVERICK_ADMIN_PASSWORD", "").strip() or None
    if password_ref:
        password = resolve_bootstrap_secret(password_ref)
    if username:
        return username, password
    if _allows_insecure_test_defaults():
        return username or "admin", password or "maverick"
    raise RuntimeError("MAVERICK_ADMIN_USERNAME is required.")


def _allows_insecure_test_defaults() -> bool:
    return os.environ.get("MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS") == "1"


def _remove_legacy_shared_provider_homes(repository_root: Path) -> None:
    """Remove pre-session provider homes that are no longer valid runtime state."""
    workspaces_root = repository_root / "workspaces"
    if not workspaces_root.is_dir():
        return
    for candidate in workspaces_root.glob("*/runtime/codex-home"):
        try:
            if candidate.is_symlink() or candidate.is_file():
                candidate.unlink()
            elif candidate.is_dir():
                shutil.rmtree(candidate)
        except OSError:
            continue
