from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime
import unittest

from core.providers.agentic_migration import migrate_agentic_runtime_schema
from core.providers.agentic_profiles import (
    build_pinned_execution_binding,
    ensure_codex_workspace_profile,
)
from core.providers.errors import AgenticProfileConflictError
from core.providers.models import ProviderSelection
from core.providers.service import builtin_provider_registry, resolve_provider_for_runtime_session
from core.providers.store import ProviderCollections, ProviderDocumentStore
from core.runtime.errors import RuntimeProviderStateError
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from tests.support.collections import FakeCollection


NOW = datetime(2026, 8, 16, tzinfo=UTC)


class AgenticProfilesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.provider_collections = ProviderCollections(
            definitions=FakeCollection(),
            bindings=FakeCollection(),
            selections=FakeCollection(),
            agentic_profile_definitions=FakeCollection(),
            agentic_profile_definition_statuses=FakeCollection(),
            workspace_agentic_profile_bindings=FakeCollection(),
            agentic_migrations=FakeCollection(),
        )
        self.provider_store = ProviderDocumentStore(self.provider_collections)
        self.registry = builtin_provider_registry()
        self.codex = self.registry.get_provider_definition("codex")

    def selection(self, *, model_id: str = "gpt-5.6-sol") -> ProviderSelection:
        return ProviderSelection(
            selection_id="default:codex",
            workspace_id="default",
            provider_id="codex",
            binding_id=None,
            selection_scope="workspace_default",
            selection_reason="test",
            created_at=NOW,
            updated_at=NOW,
            model_id=model_id,
            model_reasoning_effort="high",
        )

    def test_definition_is_installation_scoped_and_workspace_state_is_separate(self) -> None:
        profile, binding = ensure_codex_workspace_profile(
            self.provider_store,
            definition=self.codex,
            selection=self.selection(),
            now=NOW,
        )

        self.assertNotIn("workspace_id", asdict(profile))
        self.assertNotIn("credential_binding_id", asdict(profile))
        self.assertEqual(binding.workspace_id, "default")
        self.assertEqual(binding.definition_id, profile.definition_id)

    def test_workspace_binding_compare_and_set_rejects_stale_revision(self) -> None:
        _profile, binding = ensure_codex_workspace_profile(
            self.provider_store,
            definition=self.codex,
            selection=self.selection(),
            now=NOW,
        )
        updated = replace(binding, enabled=False, revision=1)
        self.provider_store.save_workspace_agentic_profile_binding(updated, expected_revision=0)

        with self.assertRaises(AgenticProfileConflictError):
            self.provider_store.save_workspace_agentic_profile_binding(
                replace(updated, enabled=True, revision=1),
                expected_revision=0,
            )

    def test_session_resolution_remains_pinned_after_workspace_default_changes(self) -> None:
        original = self.selection(model_id="gpt-5.6-sol")
        self.provider_store.save_provider_selection(original)
        ensure_codex_workspace_profile(
            self.provider_store,
            definition=self.codex,
            selection=original,
            now=NOW,
        )
        binding = build_pinned_execution_binding(
            self.provider_store,
            self.registry,
            session_id="session-a",
            workspace_id="default",
            execution_mode="full-access",
            now=NOW,
        )
        changed = replace(original, model_id="gpt-5.6-mini", updated_at=replace_time(NOW))
        self.provider_store.save_provider_selection(changed)
        ensure_codex_workspace_profile(
            self.provider_store,
            definition=self.codex,
            selection=changed,
            now=replace_time(NOW),
        )
        session = runtime_session(execution_binding=binding)

        _definition, selection = resolve_provider_for_runtime_session(
            self.provider_store,
            session=session,
            registry=self.registry,
        )

        self.assertEqual(selection.model_id if selection else None, "gpt-5.6-sol")
        self.assertEqual(session.execution_binding.binding_digest, binding.binding_digest)

    def test_migration_is_idempotent_and_preserves_legacy_continuation(self) -> None:
        selection = self.selection()
        self.provider_store.save_provider_selection(selection)
        session_collection = FakeCollection()
        provider_states = FakeCollection()
        runtime_store = RuntimeDocumentStore(
            RuntimeCollections(
                sessions=session_collection,
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
                provider_states=provider_states,
            )
        )
        legacy = runtime_session(execution_binding=None, provider_thread_id="legacy-thread")
        session_collection.update_one(
            {"session_id": legacy.session_id, "workspace_id": legacy.workspace_id},
            {"$set": asdict(legacy)},
            upsert=True,
        )

        first = migrate_agentic_runtime_schema(
            self.provider_store,
            runtime_store,
            self.registry,
            now=NOW,
        )
        second = migrate_agentic_runtime_schema(
            self.provider_store,
            runtime_store,
            self.registry,
            now=replace_time(NOW),
        )

        migrated = runtime_store.get_session("session-a")
        state = runtime_store.get_provider_state("session-a")
        self.assertTrue(migrated.execution_binding.legacy_inferred)
        self.assertEqual(state.provider_thread_id, "legacy-thread")
        self.assertEqual(first.summary_digest, second.summary_digest)
        self.assertEqual(len(provider_states.documents), 1)
        with self.assertRaises(RuntimeProviderStateError):
            runtime_store.initialize_provider_state(replace(state, provider_thread_id="other"))


def runtime_session(
    *,
    execution_binding,
    provider_thread_id: str | None = None,
) -> RuntimeSessionRecord:
    return RuntimeSessionRecord(
        session_id="session-a",
        workspace_id="default",
        agent_id="chat",
        status="running",
        requested_mode="full-access",
        effective_mode="full-access",
        workspace_root="/workspace",
        workdir="/workspace",
        runtime_root="/runtime/session-a",
        started_at=NOW,
        updated_at=NOW,
        ended_at=None,
        last_progress_at=NOW,
        execution_binding=execution_binding,
        provider_id="codex",
        provider_thread_id=provider_thread_id,
    )


def replace_time(value: datetime) -> datetime:
    return value.replace(second=value.second + 1)


if __name__ == "__main__":
    unittest.main()
