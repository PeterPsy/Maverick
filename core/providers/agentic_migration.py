"""Idempotent migration from workspace provider defaults to pinned sessions."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import hashlib
import json

from core.providers.agentic_models import (
    AgenticMigrationRecord,
    WorkspaceAgenticProfileBinding,
)
from core.providers.agentic_profiles import (
    build_pinned_execution_binding,
)
from core.providers.agentic_default_migration import migrate_legacy_codex_defaults
from core.providers.agentic_workspace_admin import (
    save_workspace_agentic_binding,
)
from core.providers.errors import AgenticProfileError, CapabilityCertificateError, ProviderNotFoundError
from core.providers.provider_registry import ProviderRegistry
from core.providers.store import ProviderStore
from core.runtime.errors import RuntimeProviderStateError
from core.runtime.authority import intersect_runtime_policies
from core.runtime.execution_binding import canonical_digest
from core.runtime.provider_state import RuntimeProviderState
from core.runtime.store import RuntimeStore


AGENTIC_SCHEMA_MIGRATION_ID = "agentic-runtime-schema-v2"
AGENTIC_SCHEMA_VERSION = "2"


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

    migrate_legacy_codex_defaults(provider_store, registry, now=timestamp)

    from core.providers.native_agent_reconciliation import refresh_codex_native_catalog

    refresh_codex_native_catalog(registry, store=provider_store, now=timestamp)
    sessions = [session for session in runtime_store.list_all_sessions() if session.runtime_mode == "agentic"]
    inferred_session_count = 0
    for session in sessions:
        binding = session.execution_binding
        if binding is None:
            selection = provider_store.get_provider_selection(session.workspace_id)
            if selection is None or selection.provider_id != "codex":
                continue
            try:
                binding = build_pinned_execution_binding(
                    provider_store, registry, session_id=session.session_id,
                    workspace_id=session.workspace_id, execution_mode=session.effective_mode,
                    reasoning_effort=selection.model_reasoning_effort, legacy_inferred=True, now=timestamp,
                )
            except (AgenticProfileError, CapabilityCertificateError):
                # Unavailable/uncertified legacy sessions must not break host
                # startup or acquire a substitute model's authority.
                continue
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
    workspace_ids = {
        "default",
        *(selection.workspace_id for selection in provider_store.list_provider_selections()),
        *(session.workspace_id for session in sessions),
    }
    _roll_forward_enabled_codex_bindings(
        provider_store,
        registry,
        workspace_ids=workspace_ids,
        now=timestamp,
    )
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
        "certificates": sorted(
            item.certificate_id for item in provider_store.list_capability_certificates()
        ),
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


def _roll_forward_enabled_codex_bindings(
    provider_store: ProviderStore,
    registry: ProviderRegistry,
    *,
    workspace_ids: set[str],
    now: datetime,
) -> None:
    from core.providers.agentic_profiles import publish_codex_agentic_profile
    from core.providers.certificate_projection import certificate_profile_status

    provider = registry.get_provider_definition("codex")
    current_profiles = {}
    for model in provider.model_options:
        profile = publish_codex_agentic_profile(provider_store, definition=provider, model_id=model.model_id, now=now)
        try:
            certificate = provider_store.get_capability_certificate(profile.capability_certificate_id)
        except ProviderNotFoundError:
            continue
        if certificate_profile_status(
            certificate, provider_store.get_capability_certificate_status(certificate.certificate_id),
            definition=profile, adapter=registry.get_agentic_runtime_adapter("codex"), store=provider_store, now=now,
        ) == "active":
            current_profiles[profile.definition_id] = profile
    for workspace_id in sorted(workspace_ids):
        bindings = provider_store.list_workspace_agentic_profile_bindings(workspace_id)
        sources_by_authority: dict[
            tuple[str, str], WorkspaceAgenticProfileBinding
        ] = {}
        for source in bindings:
            current = current_profiles.get(source.definition_id)
            if not source.enabled or current is None or source.definition_revision == current.revision:
                continue
            try:
                definition = provider_store.get_agentic_profile_definition(
                    source.definition_id,
                    source.definition_revision,
                )
            except ProviderNotFoundError:
                continue
            if definition.runtime_engine_id != "codex":
                continue
            source_key = (
                source.definition_id,
                _binding_authority_digest(source),
            )
            previous = sources_by_authority.get(source_key)
            if previous is None or _binding_roll_forward_key(source) > _binding_roll_forward_key(
                previous
            ):
                sources_by_authority[source_key] = source
        for source in sorted(
            sources_by_authority.values(),
            key=lambda item: (
                item.definition_id,
                _binding_authority_digest(item),
                item.binding_id,
            ),
        ):
            current = current_profiles[source.definition_id]
            if any(
                not item.enabled
                and item.definition_id == source.definition_id
                and item.updated_at >= source.updated_at
                and (
                    item.binding_id == _rolled_binding_id(source, item.definition_revision)
                    or _binding_authority_digest(item) == _binding_authority_digest(source)
                )
                for item in bindings
            ):
                # A later operator disable is a tombstone for this lineage,
                # even after another catalog epoch or a policy edit on it.
                continue
            if (
                source.egress_policy_id != current.egress_policy_id
                or source.egress_policy_revision != current.egress_policy_revision
                or canonical_digest(
                    intersect_runtime_policies(
                        current.policy_ceiling,
                        source.workspace_policy_ceiling,
                    )
                )
                != canonical_digest(source.workspace_policy_ceiling)
            ):
                continue
            if any(_binding_matches_current_source(item, current, source) for item in bindings):
                continue
            policy = source.workspace_policy_ceiling
            binding_id = _rolled_binding_id(source, current.revision)
            existing = next(
                (item for item in bindings if item.binding_id == binding_id),
                None,
            )
            saved = save_workspace_agentic_binding(
                provider_store,
                registry,
                workspace_id=workspace_id,
                definition_id=current.definition_id,
                definition_revision=current.revision,
                credential_binding_id=source.credential_binding_id,
                enabled=True,
                is_default=source.is_default,
                actor_policy=source.actor_policy,
                policy_patch={
                    "max_steps_per_turn": policy.max_steps_per_turn,
                    "max_tool_calls_per_turn": policy.max_tool_calls_per_turn,
                    "max_wall_time_seconds": policy.max_wall_time_seconds,
                    "max_output_tokens": policy.max_output_tokens,
                    "max_estimated_cost_microusd": policy.max_estimated_cost_microusd,
                    "allowed_remote_data_classes": list(policy.allowed_remote_data_classes),
                    "tool_access_enabled": policy.tool_handle_mode != "none",
                    "require_confirmation_for_mutating": policy.require_confirmation_for_mutating,
                    "require_confirmation_for_destructive": policy.require_confirmation_for_destructive,
                },
                binding_id=binding_id,
                expected_revision=(
                    None if existing is None else existing.revision
                ),
                now=now,
            )
            if saved.workspace_policy_ceiling != policy:
                saved = provider_store.save_workspace_agentic_profile_binding(
                    replace(
                        saved,
                        workspace_policy_ceiling=policy,
                        revision=saved.revision + 1,
                        updated_at=now,
                    ),
                    expected_revision=saved.revision,
                )
            bindings = [
                item for item in bindings if item.binding_id != saved.binding_id
            ]
            bindings.append(saved)


def _binding_roll_forward_key(
    binding: WorkspaceAgenticProfileBinding,
) -> tuple[int, bool, datetime, int, str]:
    try:
        definition_revision = int(binding.definition_revision.split(".", 1)[0])
    except (TypeError, ValueError):
        definition_revision = -1
    return (
        definition_revision,
        binding.is_default,
        binding.updated_at,
        binding.revision,
        binding.binding_id,
    )


def _binding_authority_digest(binding: WorkspaceAgenticProfileBinding) -> str:
    return canonical_digest(
        {
            "credential_binding_id": binding.credential_binding_id,
            "actor_policy": binding.actor_policy,
            "workspace_policy_ceiling": binding.workspace_policy_ceiling,
            "egress_policy_id": binding.egress_policy_id,
            "egress_policy_revision": binding.egress_policy_revision,
        }
    )


def _binding_matches_current_source(
    binding: WorkspaceAgenticProfileBinding,
    current,
    source: WorkspaceAgenticProfileBinding,
) -> bool:
    return (
        binding.definition_id == current.definition_id
        and binding.definition_revision == current.revision
        and _binding_authority_digest(binding) == _binding_authority_digest(source)
    )


def _rolled_binding_id(
    source: WorkspaceAgenticProfileBinding,
    target_revision: str,
) -> str:
    digest = hashlib.sha256(
        (
            f"{source.workspace_id}\0{source.definition_id}\0{target_revision}\0"
            f"{_binding_authority_digest(source)}"
        ).encode("utf-8")
    ).hexdigest()[:20]
    return f"workspace-agentic-rollforward-{digest}"
