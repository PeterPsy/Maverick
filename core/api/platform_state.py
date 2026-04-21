"""Runtime bootstrap state for the minimal hosted Maverick v3 platform."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path

from core.api.app_events import AppEventBus
from core.api.application import create_application
from core.apps.store import AppCollections, MongoAppStore
from core.identity.service import bootstrap_default_admin
from core.identity.store import IdentityCollections, MongoIdentityStore
from core.observability.store import MongoObservabilityStore, ObservabilityCollections
from core.providers.service import configure_workspace_provider
from core.recovery.backend_restart import recover_interrupted_runtime_turns_after_backend_restart
from core.providers.store import MongoProviderStore, ProviderCollections
from core.recovery.store import MongoRecoveryStore, RecoveryCollections
from core.runtime.event_bus import RuntimeEventBus
from core.runtime.store import MongoRuntimeStore, RuntimeCollections
from core.secrets.store import MongoSecretStore, SecretCollections
from core.shared.in_memory_collection import InMemoryCollection
from core.shared.json_file_collection import JsonFileCollection
from core.shared.repository import discover_repository_root
from core.workspaces.store import MongoWorkspaceStore, WorkspaceCollections


@dataclass(frozen=True)
class PlatformState:
    """Group the control-plane stores used by the local hosted platform."""

    repository_root: Path
    workspace_store: MongoWorkspaceStore
    identity_store: MongoIdentityStore
    app_store: MongoAppStore
    provider_store: MongoProviderStore
    runtime_store: MongoRuntimeStore
    runtime_event_bus: RuntimeEventBus
    app_event_bus: AppEventBus
    secret_store: MongoSecretStore
    recovery_store: MongoRecoveryStore
    observability_store: MongoObservabilityStore
    root_shell_app_id: str


def bootstrap_platform_state(*, start_path: Path | None = None, now: datetime | None = None) -> PlatformState:
    """Build in-memory platform state and install first-boot built-in apps."""
    repository_root = discover_repository_root(start_path=start_path)
    control_state_root = repository_root / ".maverick" / "local-state"
    app_state_root = control_state_root / "apps"
    workspace_state_root = control_state_root / "workspaces"
    identity_state_root = control_state_root / "identity"
    workspace_store = MongoWorkspaceStore(
        WorkspaceCollections(
            workspaces=JsonFileCollection(workspace_state_root / "workspaces.json"),
            memberships=JsonFileCollection(workspace_state_root / "memberships.json"),
            governance=JsonFileCollection(workspace_state_root / "governance.json"),
            quotas=JsonFileCollection(workspace_state_root / "quotas.json"),
            active_workspace_selections=JsonFileCollection(workspace_state_root / "active_workspace_selections.json"),
        )
    )
    identity_store = MongoIdentityStore(
        IdentityCollections(
            users=JsonFileCollection(identity_state_root / "users.json"),
            credentials=JsonFileCollection(identity_state_root / "credentials.json"),
            auth_sessions=JsonFileCollection(identity_state_root / "auth_sessions.json"),
        )
    )
    app_store = MongoAppStore(
        AppCollections(
            app_sources=JsonFileCollection(app_state_root / "app_sources.json"),
            workspace_local_app_projects=JsonFileCollection(app_state_root / "workspace_local_app_projects.json"),
            workspace_app_bindings=JsonFileCollection(app_state_root / "workspace_app_bindings.json"),
        )
    )
    provider_store = MongoProviderStore(
        ProviderCollections(
            definitions=InMemoryCollection(),
            bindings=InMemoryCollection(),
            selections=InMemoryCollection(),
        )
    )
    runtime_state_root = control_state_root / "runtime"
    runtime_store = MongoRuntimeStore(
        RuntimeCollections(
            sessions=JsonFileCollection(runtime_state_root / "sessions.json"),
            turns=JsonFileCollection(runtime_state_root / "turns.json"),
            events=JsonFileCollection(runtime_state_root / "events.json", append_only_upserts=True),
            processes=JsonFileCollection(runtime_state_root / "processes.json"),
            states=JsonFileCollection(runtime_state_root / "states.json"),
        )
    )
    runtime_event_bus = RuntimeEventBus()
    app_event_bus = AppEventBus()
    secret_state_root = control_state_root / "secrets"
    secret_store = MongoSecretStore(
        SecretCollections(
            secrets=JsonFileCollection(secret_state_root / "secrets.json"),
            values=JsonFileCollection(secret_state_root / "values.json"),
            bindings=JsonFileCollection(secret_state_root / "bindings.json"),
        )
    )
    recovery_store = MongoRecoveryStore(
        RecoveryCollections(
            failures=InMemoryCollection(),
            intents=InMemoryCollection(),
            health_results=InMemoryCollection(),
        )
    )
    observability_store = MongoObservabilityStore(
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
        now=now,
    )
    configure_workspace_provider(
        provider_store,
        workspace_id="default",
        provider_id="codex",
        observability_store=observability_store,
        now=now,
    )
    bootstrap_default_admin(
        identity_store,
        workspace_store,
        username=os.environ.get("MAVERICK3_ADMIN_USERNAME", "admin"),
        password=os.environ.get("MAVERICK3_ADMIN_PASSWORD", "maverick3"),
        now=now,
    )
    state = PlatformState(
        repository_root=repository_root,
        workspace_store=workspace_store,
        identity_store=identity_store,
        app_store=app_store,
        provider_store=provider_store,
        runtime_store=runtime_store,
        runtime_event_bus=runtime_event_bus,
        app_event_bus=app_event_bus,
        secret_store=secret_store,
        recovery_store=recovery_store,
        observability_store=observability_store,
        root_shell_app_id=os.environ.get("MAVERICK3_ROOT_SHELL_APP_ID", "base-shell").strip() or "base-shell",
    )
    recover_interrupted_runtime_turns_after_backend_restart(state)
    return state
