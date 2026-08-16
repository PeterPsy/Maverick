"""Idempotent migration from workspace provider defaults to pinned sessions."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import hashlib
import json

from core.providers.agentic_models import AgenticMigrationRecord
from core.providers.agentic_profiles import (
    build_pinned_execution_binding,
    ensure_codex_workspace_profile,
)
from core.providers.provider_registry import ProviderRegistry
from core.providers.store import ProviderStore
from core.runtime.errors import RuntimeProviderStateError
from core.runtime.provider_state import RuntimeProviderState
from core.runtime.store import RuntimeStore


AGENTIC_SCHEMA_MIGRATION_ID = "agentic-runtime-schema-v1"
AGENTIC_SCHEMA_VERSION = "1"


def migrate_agentic_runtime_schema(
    provider_store: ProviderStore,
    runtime_store: RuntimeStore,
    registry: ProviderRegistry,
    *,
    now: datetime | None = None,
) -> AgenticMigrationRecord:
    """Publish legacy Codex profiles and pin every migratable agentic session."""
    timestamp = now or datetime.now(tz=UTC)
    previous = provider_store.get_agentic_migration(AGENTIC_SCHEMA_MIGRATION_ID)
    created_at = previous.created_at if previous is not None else timestamp
    provider_store.save_agentic_migration(
        AgenticMigrationRecord(
            migration_id=AGENTIC_SCHEMA_MIGRATION_ID,
            schema_version=AGENTIC_SCHEMA_VERSION,
            status="started",
            profile_count=0,
            binding_count=0,
            session_count=0,
            inferred_session_count=0,
            summary_digest=_summary_digest({"status": "started"}),
            created_at=created_at,
            updated_at=timestamp,
        )
    )

    for selection in provider_store.list_provider_selections():
        if selection.provider_id != "codex":
            continue
        ensure_codex_workspace_profile(
            provider_store,
            definition=registry.get_provider_definition("codex"),
            selection=selection,
            now=timestamp,
        )

    sessions = [session for session in runtime_store.list_all_sessions() if session.runtime_mode == "agentic"]
    inferred_session_count = 0
    for session in sessions:
        binding = session.execution_binding
        if binding is None:
            selection = provider_store.get_provider_selection(session.workspace_id)
            if selection is None or selection.provider_id != "codex":
                continue
            binding = build_pinned_execution_binding(
                provider_store,
                registry,
                session_id=session.session_id,
                workspace_id=session.workspace_id,
                execution_mode=session.effective_mode,
                legacy_inferred=True,
                now=timestamp,
            )
            runtime_store.save_session(
                replace(
                    session,
                    execution_binding=binding,
                    provider_id=binding.runtime_engine_id,
                )
            )
            inferred_session_count += 1
        elif binding.legacy_inferred:
            inferred_session_count += 1
        try:
            runtime_store.get_provider_state(session.session_id)
        except RuntimeProviderStateError:
            runtime_store.initialize_provider_state(
                RuntimeProviderState(
                    session_id=session.session_id,
                    workspace_id=session.workspace_id,
                    runtime_engine_id=binding.runtime_engine_id,
                    model_provider_id=binding.model_provider_id,
                    continuation_id=session.provider_thread_id,
                    provider_thread_id=session.provider_thread_id,
                    provider_request_id=None,
                    provider_private_envelope=None,
                    revision=0,
                    turn_generation=None,
                    updated_at=timestamp,
                )
            )

    definitions = provider_store.list_agentic_profile_definitions()
    workspace_ids = {selection.workspace_id for selection in provider_store.list_provider_selections()}
    bindings = [
        binding
        for workspace_id in workspace_ids
        for binding in provider_store.list_workspace_agentic_profile_bindings(workspace_id)
    ]
    summary = {
        "profiles": sorted(f"{item.definition_id}:{item.revision}" for item in definitions),
        "bindings": sorted(f"{item.binding_id}:{item.revision}" for item in bindings),
        "sessions": sorted(session.session_id for session in sessions),
        "inferred_session_count": inferred_session_count,
    }
    completed = AgenticMigrationRecord(
        migration_id=AGENTIC_SCHEMA_MIGRATION_ID,
        schema_version=AGENTIC_SCHEMA_VERSION,
        status="completed",
        profile_count=len(definitions),
        binding_count=len(bindings),
        session_count=len(sessions),
        inferred_session_count=inferred_session_count,
        summary_digest=_summary_digest(summary),
        created_at=created_at,
        updated_at=timestamp,
    )
    return provider_store.save_agentic_migration(completed)


def _summary_digest(summary: dict[str, object]) -> str:
    encoded = json.dumps(summary, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
