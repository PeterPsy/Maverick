"""Runtime bootstrap state for the minimal hosted Maverick platform."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import shutil

from core.api.app_events import AppEventBus
from core.api.application import create_application
from core.api.control_store import ControlPlaneCollections, ControlStoreSettings, build_control_plane_collections
from core.api.persistence_cleanup_worker import run_pending_cleanup_plans
from core.apps.store import AppDocumentStore
from core.apps.runtime_root_capabilities import RuntimeRootCapabilityStore
from core.apps.sidecar_browser_sessions import SidecarBrowserSessionStore
from core.identity.service import bootstrap_default_admin
from core.identity.store import IdentityDocumentStore
from core.inter_agent.store import InterAgentDocumentStore, build_inter_agent_document_store
from core.observability.store import ObservabilityDocumentStore, ObservabilityCollections
from core.providers.provider_codex import refresh_workspace_maverick_wrappers
from core.recovery.backend_restart import recover_interrupted_runtime_turns_after_backend_restart
from core.providers.store import ProviderDocumentStore
from core.recovery.store import RecoveryDocumentStore, RecoveryCollections
from core.runtime.event_collection import RuntimeEventJsonCollection
from core.runtime.event_bus import RuntimeEventBus
from core.runtime.thread_event_bus import RuntimeThreadEventBus
from core.runtime.session_collection import RuntimeSessionJsonCollection
from core.runtime.store import RuntimeDocumentStore, RuntimeCollections
from core.runtime.workspace_collection import WorkspaceRuntimeJsonCollection
from core.secrets.bootstrap import resolve_bootstrap_secret
from core.secrets.store import SecretDocumentStore
from core.shared.in_memory_collection import InMemoryCollection
from core.shared.repository import discover_repository_root
from core.workspaces.store import WorkspaceDocumentStore


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
    runtime_store: RuntimeDocumentStore
    inter_agent_store: InterAgentDocumentStore
    runtime_event_bus: RuntimeEventBus
    runtime_thread_event_bus: RuntimeThreadEventBus
    app_event_bus: AppEventBus
    secret_store: SecretDocumentStore
    recovery_store: RecoveryDocumentStore
    observability_store: ObservabilityDocumentStore
    sidecar_browser_sessions: SidecarBrowserSessionStore
    runtime_root_capabilities: RuntimeRootCapabilityStore
    root_shell_app_id: str


def bootstrap_platform_state(
    *,
    start_path: Path | None = None,
    now: datetime | None = None,
    recover_backend_restart: bool = False,
    install_builtin_apps: bool = True,
    register_builtin_provider_definitions: bool = True,
    bootstrap_admin: bool = True,
) -> PlatformState:
    """Build in-memory platform state and optionally run host bootstrap work."""
    repository_root = discover_repository_root(start_path=start_path)
    _remove_legacy_shared_provider_homes(repository_root)
    refresh_workspace_maverick_wrappers(repository_root)
    control_settings = ControlStoreSettings.from_environment(repository_root=repository_root)
    run_pending_cleanup_plans(repository_root=repository_root, active_settings=control_settings)
    control_collections = build_control_plane_collections(control_settings)
    workspace_store = WorkspaceDocumentStore(control_collections.workspace)
    identity_store = IdentityDocumentStore(control_collections.identity)
    app_store = AppDocumentStore(control_collections.apps)
    provider_store = ProviderDocumentStore(control_collections.provider)
    runtime_sessions = RuntimeSessionJsonCollection(start_path=repository_root, filename="session.json")
    runtime_turns = RuntimeSessionJsonCollection(start_path=repository_root, filename="turns.json")
    runtime_events = RuntimeEventJsonCollection(start_path=repository_root)
    runtime_processes = RuntimeSessionJsonCollection(start_path=repository_root, filename="processes.json")
    runtime_states = RuntimeSessionJsonCollection(start_path=repository_root, filename="state.json")
    runtime_threads = WorkspaceRuntimeJsonCollection(start_path=repository_root, filename="threads.json")
    runtime_client_messages = WorkspaceRuntimeJsonCollection(start_path=repository_root, filename="client_messages.json")
    runtime_app_streams = WorkspaceRuntimeJsonCollection(start_path=repository_root, filename="app_streams.json")
    runtime_app_stream_events = RuntimeSessionJsonCollection(
        start_path=repository_root,
        filename="app_stream_events.json",
    )
    runtime_store = RuntimeDocumentStore(
        RuntimeCollections(
            sessions=runtime_sessions,
            turns=runtime_turns,
            events=runtime_events,
            processes=runtime_processes,
            states=runtime_states,
            threads=runtime_threads,
            client_messages=runtime_client_messages,
            app_streams=runtime_app_streams,
            app_stream_events=runtime_app_stream_events,
            api_tokens=control_collections.runtime_api_tokens,
        )
    )
    inter_agent_store = build_inter_agent_document_store(start_path=repository_root)
    runtime_event_bus = RuntimeEventBus()
    runtime_thread_event_bus = RuntimeThreadEventBus()
    app_event_bus = AppEventBus()
    secret_store = SecretDocumentStore(control_collections.secrets)
    recovery_store = RecoveryDocumentStore(
        RecoveryCollections(
            failures=InMemoryCollection(),
            intents=InMemoryCollection(),
            health_results=InMemoryCollection(),
        )
    )
    observability_store = ObservabilityDocumentStore(
        ObservabilityCollections(
            events=InMemoryCollection(),
            audit=InMemoryCollection(),
            metrics=InMemoryCollection(),
        )
    )
    create_application(
        start_path=repository_root,
        workspace_store=workspace_store,
        app_store=app_store,
        provider_store=provider_store,
        install_builtin_apps=install_builtin_apps,
        register_providers=register_builtin_provider_definitions,
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
    state = PlatformState(
        repository_root=repository_root,
        control_store_settings=control_settings,
        control_plane_collections=control_collections,
        workspace_store=workspace_store,
        identity_store=identity_store,
        app_store=app_store,
        provider_store=provider_store,
        runtime_store=runtime_store,
        inter_agent_store=inter_agent_store,
        runtime_event_bus=runtime_event_bus,
        runtime_thread_event_bus=runtime_thread_event_bus,
        app_event_bus=app_event_bus,
        secret_store=secret_store,
        recovery_store=recovery_store,
        observability_store=observability_store,
        sidecar_browser_sessions=SidecarBrowserSessionStore(),
        runtime_root_capabilities=RuntimeRootCapabilityStore(),
        root_shell_app_id=os.environ.get("MAVERICK_ROOT_SHELL_APP_ID", "base-shell").strip() or "base-shell",
    )
    if recover_backend_restart:
        recover_interrupted_runtime_turns_after_backend_restart(state)
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
