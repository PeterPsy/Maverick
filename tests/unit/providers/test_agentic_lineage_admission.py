"""Explicit admission decisions survive transitive ancestry and policy edits."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
import tempfile
import unittest

from core.providers.agentic_models import WorkspaceAgenticProfileBinding, default_actor_selection_policy, codex_runtime_policy
from core.providers.agentic_lineage_admission import lineage_admission_disabled, record_lineage_decision, rolled_binding_id
from core.providers.store import ProviderCollections, ProviderDocumentStore
from core.shared.in_memory_collection import InMemoryCollection
from core.shared.json_file_collection import JsonFileCollection


class AgenticLineageAdmissionTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(tz=UTC)
        self.rows = {}
        self.a = self.save(WorkspaceAgenticProfileBinding(
            binding_id="A", workspace_id="default", definition_id="model", definition_revision="A",
            credential_binding_id=None, enabled=True, is_default=False, actor_policy=default_actor_selection_policy(),
            workspace_policy_ceiling=codex_runtime_policy(), egress_policy_id="local", egress_policy_revision="1",
            revision=0, created_at=self.now, updated_at=self.now,
        ))

    def save(self, binding, *, operator=True):
        self.now += timedelta(seconds=1)
        existing = self.rows.get(binding.binding_id)
        saved = record_lineage_decision(
            replace(binding, updated_at=self.now), existing, list(self.rows.values()),
            operator_decision=operator, now=self.now,
        )
        self.rows[binding.binding_id] = saved
        return saved

    def roll(self, source, revision):
        return self.save(replace(source, binding_id=rolled_binding_id(source, revision),
                                 definition_revision=revision, lineage_binding_ids=(),
                                 admission_enabled_at=None, admission_disabled_at=None), operator=False)

    def test_policy_edits_preserve_transitive_ancestry_and_never_count_as_enable(self):
        b = self.roll(self.a, "B")
        b = self.save(replace(b, workspace_policy_ceiling=replace(b.workspace_policy_ceiling, allow_shell=False)))
        c = self.roll(b, "C")
        c = self.save(replace(c, enabled=False))
        a = self.save(replace(self.a, credential_binding_id="changed-credential"))
        self.assertTrue(lineage_admission_disabled(a, list(self.rows.values())))
        self.assertIsNone(b.admission_enabled_at)
        self.assertIn(a.binding_id, c.lineage_binding_ids)
        a = self.save(replace(a, enabled=False))
        a = self.save(replace(a, enabled=True))
        self.assertFalse(lineage_admission_disabled(a, list(self.rows.values())))
        self.assertFalse(self.rows[c.binding_id].enabled)

    def test_disabled_other_authority_does_not_block_an_independent_binding(self):
        unrelated = self.save(replace(self.a, binding_id="independent", credential_binding_id="other",
                                      lineage_binding_ids=(), admission_enabled_at=None, admission_disabled_at=None))
        self.a = self.save(replace(self.a, enabled=False))
        self.assertFalse(lineage_admission_disabled(unrelated, list(self.rows.values())))

    def test_decisions_and_membership_round_trip_through_the_json_store(self):
        b = self.save(replace(self.roll(self.a, "B"), enabled=False))
        with tempfile.TemporaryDirectory() as directory:
            def store():
                return ProviderDocumentStore(ProviderCollections(
                    definitions=InMemoryCollection(), bindings=InMemoryCollection(), selections=InMemoryCollection(),
                    workspace_agentic_profile_bindings=JsonFileCollection(Path(directory) / "bindings.json"),
                ))
            writer = store()
            for row in self.rows.values():
                writer.save_workspace_agentic_profile_binding(row, expected_revision=None)
            reader = store()
            self.assertEqual(reader.get_workspace_agentic_profile_binding(b.binding_id), b)
            self.assertTrue(lineage_admission_disabled(
                reader.get_workspace_agentic_profile_binding("A"), reader.list_workspace_agentic_profile_bindings("default")))
