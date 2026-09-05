"""Cold bootstrap must not replay legacy selections over operator decisions."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import unittest
from unittest.mock import patch

from core.providers.agentic_migration import migrate_agentic_runtime_schema
from core.providers.agentic_profiles import build_pinned_execution_binding, ensure_codex_workspace_profile
from core.providers.models import ProviderSelection
from core.providers.service import effective_provider_registry
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from tests.support.collections import FakeCollection
from tests.support.maverick_agent_onboarding import provider_store
from tests.support.native_agent_catalog import codex_snapshot


class AgenticBootstrapDefaultsTest(unittest.TestCase):
    def setUp(self):
        discovery = patch("core.providers.native_agent_reconciliation.discover_codex_native_catalog",
                          return_value=codex_snapshot("gpt-5.6-sol"))
        discovery.start()
        self.addCleanup(discovery.stop)
        self.now = datetime.now(tz=UTC)
        self.store = provider_store()
        self.registry = effective_provider_registry(self.store)
        selection = ProviderSelection(
            selection_id="legacy", workspace_id="default", provider_id="codex", binding_id=None,
            selection_scope="workspace_default", selection_reason="legacy default", model_id="gpt-5.6-sol",
            model_reasoning_effort=None, created_at=self.now, updated_at=self.now,
        )
        self.store.save_provider_selection(selection)
        _profile, self.legacy = ensure_codex_workspace_profile(
            self.store, definition=self.registry.get_provider_definition("codex"), selection=selection,
        )
        self.runtime = RuntimeDocumentStore(RuntimeCollections(**{
            name: FakeCollection() for name in ("sessions", "turns", "events", "processes", "states", "threads", "provider_states")
        }))

    def bootstrap(self):
        migrate_agentic_runtime_schema(self.store, self.runtime, self.registry, now=self.now + timedelta(seconds=2))

    def bindings(self):
        return self.store.list_workspace_agentic_profile_bindings("default")

    def add_operator_default(self):
        operator = replace(self.legacy, binding_id="explicit-operator-default", revision=0,
                           created_at=self.now + timedelta(seconds=1), updated_at=self.now + timedelta(seconds=1))
        self.store.save_workspace_agentic_profile_binding(operator, expected_revision=None)
        return operator

    def test_restart_preserves_a_later_operator_default_without_repromoting_legacy(self):
        self.store.save_workspace_agentic_profile_binding(
            replace(self.legacy, is_default=False, revision=1), expected_revision=0,
        )
        self.add_operator_default()
        before = self.bindings()
        self.bootstrap()
        self.bootstrap()
        self.assertEqual(self.bindings(), before)

    def test_restart_does_not_reenable_an_explicitly_disabled_legacy_binding(self):
        self.store.save_workspace_agentic_profile_binding(replace(
            self.legacy, enabled=False, is_default=False, revision=1,
            workspace_policy_ceiling=replace(self.legacy.workspace_policy_ceiling, allow_filesystem_read=False),
        ), expected_revision=0)
        before = self.bindings()
        self.bootstrap()
        self.assertEqual(self.bindings(), before)

    def test_restart_repairs_only_the_duplicate_legacy_default_flag(self):
        operator = self.add_operator_default()
        self.bootstrap()
        repaired = self.store.get_workspace_agentic_profile_binding(self.legacy.binding_id)
        self.assertEqual(replace(repaired, is_default=True, revision=self.legacy.revision,
                                 updated_at=self.legacy.updated_at), self.legacy)
        self.assertFalse(repaired.is_default)
        self.assertEqual(self.store.get_workspace_agentic_profile_binding(operator.binding_id), operator)
        before = self.bindings()
        self.bootstrap()
        self.assertEqual(self.bindings(), before)
        pin = build_pinned_execution_binding(self.store, self.registry, session_id="post-bootstrap",
                                             workspace_id="default", execution_mode="sandbox")
        self.assertEqual(pin.workspace_binding_id, operator.binding_id)
