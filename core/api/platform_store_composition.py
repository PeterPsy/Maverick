"""Shared real store composition, without repository/bootstrap side effects.

Explicit roots and key loaders permit an isolated laboratory to use the same
runtime persistence, vault crypto, WAL, tool ledger and egress implementation.
"""

from datetime import UTC, datetime

from core.api.app_events import AppEventBus
from core.api.control_store import build_control_plane_collections
from core.egress.agentic_policy import AgenticEgressEvaluator
from core.apps.store import AppDocumentStore
from core.apps.runtime_root_capabilities import RuntimeRootCapabilityStore
from core.apps.sidecar_browser_sessions import SidecarBrowserSessionStore
from core.identity.store import IdentityDocumentStore
from core.inter_agent.store import build_inter_agent_document_store
from core.jobs.events import JobEventBus
from core.jobs.service import JobService
from core.jobs.store import JobDocumentStore
from core.observability.store import ObservabilityDocumentStore, ObservabilityCollections
from core.providers.service import builtin_provider_registry
from core.providers.store import ProviderDocumentStore
from core.recovery.store import RecoveryDocumentStore, RecoveryCollections
from core.runtime.app_reference_classification import build_workspace_app_reference_classification_resolver
from core.runtime.event_collection import RuntimeEventJsonCollection
from core.runtime.event_bus import RuntimeEventBus
from core.runtime.hosted_runtime_registry_builder import (
    build_builtin_maverick_agent_onboarding_catalog,
)
from core.runtime.thread_event_bus import RuntimeThreadEventBus
from core.runtime.session_collection import RuntimeSessionJsonCollection
from core.runtime.store import RuntimeDocumentStore, RuntimeCollections
from core.runtime.private_payload_store import EncryptedRuntimePrivatePayloadStore
from core.runtime.provider_private_state import ProviderPrivateStateService
from core.runtime.provider_input_admission import (
    build_runtime_provider_input_classification_resolver,
)
from core.runtime.tool_ledger import RuntimeToolLedger
from core.runtime.tool_private_payloads import EncryptedRuntimeToolPrivatePayloadStore
from core.runtime.workspace_collection import WorkspaceRuntimeJsonCollection
from core.secrets.store import SecretDocumentStore
from core.shared.in_memory_collection import InMemoryCollection
from core.usage.store import UsageDocumentStore
from core.workspaces.store import WorkspaceDocumentStore


def compose_platform_store_state(
    *, repository_root, control_settings, key_loader, keyring_loader,
    secret_collections=None, root_shell_app_id="base-shell", now=None,
    runtime_input_classification_resolver=None,
    runtime_app_reference_classification_resolver=None,
):
    from core.api.platform_state import PlatformState

    control_collections = build_control_plane_collections(control_settings)
    workspace_store = WorkspaceDocumentStore(control_collections.workspace)
    identity_store = IdentityDocumentStore(control_collections.identity)
    app_store = AppDocumentStore(control_collections.apps)
    provider_store = ProviderDocumentStore(control_collections.provider)
    provider_registry = builtin_provider_registry()
    runtime_sessions = RuntimeSessionJsonCollection(start_path=repository_root, filename="session.json")
    runtime_turns = RuntimeSessionJsonCollection(start_path=repository_root, filename="turns.json")
    runtime_events = RuntimeEventJsonCollection(start_path=repository_root)
    runtime_processes = RuntimeSessionJsonCollection(start_path=repository_root, filename="processes.json")
    runtime_states = RuntimeSessionJsonCollection(start_path=repository_root, filename="state.json")
    runtime_provider_states = RuntimeSessionJsonCollection(
        start_path=repository_root,
        filename="provider_state.json",
    )
    runtime_provider_step_journals = RuntimeSessionJsonCollection(
        start_path=repository_root,
        filename="provider_step_journal.json",
    )
    runtime_tool_invocations = RuntimeSessionJsonCollection(
        start_path=repository_root,
        filename="tool_invocations.json",
    )
    runtime_tool_confirmation_grants = RuntimeSessionJsonCollection(
        start_path=repository_root,
        filename="tool_confirmation_grants.json",
    )
    runtime_egress_decisions = RuntimeSessionJsonCollection(
        start_path=repository_root,
        filename="egress_decisions.json",
    )
    runtime_continuation_handoffs = WorkspaceRuntimeJsonCollection(
        start_path=repository_root,
        filename="continuation_handoffs.json",
    )
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
            provider_states=runtime_provider_states,
            provider_step_journals=runtime_provider_step_journals,
            tool_invocations=runtime_tool_invocations,
            tool_confirmation_grants=runtime_tool_confirmation_grants,
            egress_decisions=runtime_egress_decisions,
            continuation_handoffs=runtime_continuation_handoffs,
            api_tokens=control_collections.runtime_api_tokens,
        )
    )
    private_payload_store = EncryptedRuntimePrivatePayloadStore(
        repository_root=repository_root,
        key_loader=key_loader,
        keyring_loader=keyring_loader,
    )
    runtime_tool_ledger = RuntimeToolLedger(
        store=runtime_store,
        private_payload_store=EncryptedRuntimeToolPrivatePayloadStore(private_payload_store),
        digest_key=key_loader(),
    )
    provider_private_state_service = ProviderPrivateStateService(
        store=runtime_store,
        payload_store=private_payload_store,
    )
    inter_agent_store = build_inter_agent_document_store(start_path=repository_root)
    runtime_event_bus = RuntimeEventBus()
    runtime_thread_event_bus = RuntimeThreadEventBus()
    app_event_bus = AppEventBus()
    job_event_bus = JobEventBus()
    secret_store = SecretDocumentStore(secret_collections or control_collections.secrets,
                                       key_loader=key_loader, keyring_loader=keyring_loader)
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
    usage_store = UsageDocumentStore(control_collections.usage)
    agentic_egress_evaluator = AgenticEgressEvaluator(
        digest_key=key_loader(),
        observability_store=observability_store,
        decision_store=runtime_store,
    )
    job_service = JobService(
        JobDocumentStore(control_collections.jobs),
        event_bus=job_event_bus,
        observability_store=observability_store,
    )
    onboarding_catalog = build_builtin_maverick_agent_onboarding_catalog(now=now or datetime.now(UTC))
    state = PlatformState(
        repository_root=repository_root,
        control_store_settings=control_settings,
        control_plane_collections=control_collections,
        workspace_store=workspace_store,
        identity_store=identity_store,
        app_store=app_store,
        provider_store=provider_store,
        provider_registry=provider_registry,
        runtime_store=runtime_store,
        inter_agent_store=inter_agent_store,
        job_service=job_service,
        job_event_bus=job_event_bus,
        runtime_event_bus=runtime_event_bus,
        runtime_thread_event_bus=runtime_thread_event_bus,
        app_event_bus=app_event_bus,
        secret_store=secret_store,
        recovery_store=recovery_store,
        observability_store=observability_store,
        usage_store=usage_store,
        sidecar_browser_sessions=SidecarBrowserSessionStore(),
        runtime_root_capabilities=RuntimeRootCapabilityStore(),
        root_shell_app_id=root_shell_app_id,
        runtime_tool_ledger=runtime_tool_ledger,
        provider_private_state_service=provider_private_state_service,
        agentic_egress_evaluator=agentic_egress_evaluator,
        runtime_input_classification_resolver=(
            build_runtime_provider_input_classification_resolver(
                runtime_store=runtime_store,
                workspace_store=workspace_store,
            )
            if runtime_input_classification_resolver is None
            else runtime_input_classification_resolver
        ),
        runtime_app_reference_classification_resolver=(
            runtime_app_reference_classification_resolver
            or build_workspace_app_reference_classification_resolver(
                workspace_store
            )
        ),
        maverick_agent_onboarding_catalog=onboarding_catalog,
    )
    return state
