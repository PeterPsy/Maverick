"""Workspace attestation persistence, CAS, scope, revocation, and audit tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
import tempfile
import unittest

from core.shared.json_file_collection import JsonFileCollection
from core.workspaces.data_governance import (
    WorkspaceResourceClassification,
    WorkspaceDataGovernanceService,
    attestation_safe_projection,
    resource_classification_for_observation,
)
from core.workspaces.errors import WorkspaceDataGovernanceError
from core.workspaces.store import WorkspaceCollections, WorkspaceDocumentStore
from tests.support.collections import FakeCollection


class WorkspaceDataGovernanceTestCase(unittest.TestCase):
    def store(self, *, json_root: Path | None = None) -> WorkspaceDocumentStore:
        def collection(name: str):
            if json_root is None:
                return FakeCollection()
            return JsonFileCollection(json_root / f"{name}.json")

        return WorkspaceDocumentStore(
            WorkspaceCollections(
                workspaces=collection("workspaces"),
                memberships=collection("memberships"),
                governance=collection("governance"),
                quotas=collection("quotas"),
                active_workspace_selections=collection("active"),
                data_attestations=collection("attestations"),
                resource_classifications=collection("classifications"),
                data_governance_audits=collection("audits"),
            )
        )

    def test_attestation_is_cas_revisioned_actor_attributed_scoped_revocable_and_audited(self) -> None:
        store = self.store()
        service = WorkspaceDataGovernanceService(store)
        now = datetime(2026, 8, 26, 10, tzinfo=UTC)

        issued = service.issue_attestation(
            workspace_id="workspace-1",
            actor_id="operator-1",
            actor_kind="platform_operator",
            scope_type="resource_prefixes",
            resource_prefixes=("storage/generated", "workspace-data/records"),
            expected_revision=0,
            now=now,
        )

        self.assertTrue(issued.authoritative)
        self.assertEqual(issued.revision, 1)
        self.assertEqual(issued.attested_by_actor_id, "operator-1")
        self.assertEqual(issued.attested_at, now)
        self.assertEqual(
            issued.resource_prefixes,
            ("storage/generated", "workspace-data/records"),
        )
        self.assertTrue(issued.covers_resource("storage/generated/fixture.json"))
        self.assertFalse(issued.covers_resource("storage/generated/../real/customer.json"))
        self.assertFalse(issued.covers_resource("/storage/generated/fixture.json"))
        with self.assertRaisesRegex(WorkspaceDataGovernanceError, "attestation_revision_conflict"):
            service.issue_attestation(
                workspace_id="workspace-1",
                actor_id="operator-2",
                actor_kind="platform_operator",
                scope_type="workspace",
                expected_revision=0,
                now=now,
            )

        revoked = service.revoke_attestation(
            workspace_id="workspace-1",
            actor_id="operator-2",
            expected_revision=1,
            reason="fixture set retired",
            now=now + timedelta(minutes=1),
        )

        self.assertFalse(revoked.authoritative)
        self.assertEqual(revoked.status, "revoked")
        self.assertEqual(revoked.revision, 2)
        self.assertEqual(revoked.revoked_by_actor_id, "operator-2")
        audits = store.list_data_governance_audits(workspace_id="workspace-1")
        self.assertEqual([audit.action for audit in audits], [
            "workspace.data_attestation.issue",
            "workspace.data_attestation.revoke",
        ])
        self.assertEqual([audit.actor_id for audit in audits], ["operator-1", "operator-2"])
        self.assertEqual([audit.resulting_revision for audit in audits], [1, 2])

    def test_json_and_document_stores_round_trip_without_browser_mutation_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self.store(json_root=Path(temp_dir))
            service = WorkspaceDataGovernanceService(store)
            issued = service.issue_attestation(
                workspace_id="workspace-json",
                actor_id="operator-json",
                actor_kind="platform_operator",
                scope_type="workspace",
                expected_revision=0,
                now=datetime(2026, 8, 26, tzinfo=UTC),
            )

            reloaded_store = self.store(json_root=Path(temp_dir))
            reloaded = reloaded_store.get_data_attestation("workspace-json")
            revoked = WorkspaceDataGovernanceService(reloaded_store).revoke_attestation(
                workspace_id="workspace-json",
                actor_id="operator-revoker",
                expected_revision=1,
                reason="JSON CAS revocation fixture",
                now=datetime(2026, 8, 26, 0, 1, tzinfo=UTC),
            )
            revoked_reloaded = self.store(
                json_root=Path(temp_dir)
            ).get_data_attestation("workspace-json")
            audits_reloaded = self.store(json_root=Path(temp_dir)).list_data_governance_audits(
                workspace_id="workspace-json"
            )

        self.assertEqual(reloaded, issued)
        projection = attestation_safe_projection(reloaded)
        self.assertEqual(projection["state"], "active")
        self.assertNotIn("attested_by_actor_id", projection)
        self.assertNotIn("expected_revision", projection)
        self.assertNotIn("mutation_token", projection)
        self.assertEqual(revoked_reloaded, revoked)
        self.assertEqual(attestation_safe_projection(revoked_reloaded)["state"], "revoked")
        self.assertEqual(len(audits_reloaded), 2)

    def test_resource_classification_round_trips_with_cas_in_both_stores(self) -> None:
        now = datetime(2026, 8, 26, tzinfo=UTC)
        for use_json in (False, True):
            with self.subTest(use_json=use_json), tempfile.TemporaryDirectory() as temp_dir:
                json_root = Path(temp_dir) if use_json else None
                store = self.store(json_root=json_root)
                record = WorkspaceResourceClassification(
                    classification_id="classification-1",
                    workspace_id="workspace-1",
                    resource_kind="filesystem",
                    resource_ref="storage/generated/fixture.txt",
                    resource_identity="dev:1:ino:2",
                    resource_revision="size:7:mtime:8",
                    resource_digest="a" * 64,
                    data_class="workspace_internal_fake",
                    trust_level="trusted_actor",
                    revision=1,
                    classified_by_actor_id="operator-1",
                    classified_at=now,
                    updated_at=now,
                )
                store.save_resource_classification(record, expected_revision=0)
                reloaded_store = self.store(json_root=json_root) if use_json else store
                reloaded = reloaded_store.get_resource_classification(
                    workspace_id="workspace-1",
                    resource_kind="filesystem",
                    resource_ref="storage/generated/fixture.txt",
                )
                self.assertEqual(reloaded, record)
                observed = resource_classification_for_observation(
                    reloaded,
                    workspace_id="workspace-1",
                    resource_kind="filesystem",
                    resource_ref="storage/generated/fixture.txt",
                    resource_identity="dev:1:ino:2",
                    resource_revision="size:7:mtime:8",
                    resource_digest="a" * 64,
                    provenance="tool_result",
                )
                self.assertEqual(observed.data_class, "workspace_internal_fake")
                self.assertEqual(observed.classification_revision, 1)
                with self.assertRaisesRegex(
                    WorkspaceDataGovernanceError,
                    "resource_classification_revision_conflict",
                ):
                    reloaded_store.save_resource_classification(
                        replace(record, revision=2),
                        expected_revision=0,
                    )

    def test_legacy_resource_classification_can_never_authorize_an_observation(self) -> None:
        store = self.store()
        assert store.collections.resource_classifications is not None
        store.collections.resource_classifications.update_one(
            {
                "workspace_id": "workspace-1",
                "resource_kind": "filesystem",
                "resource_ref": "storage/generated/fixture.txt",
            },
            {
                "$set": {
                    "workspace_id": "workspace-1",
                    "resource_kind": "filesystem",
                    "resource_ref": "storage/generated/fixture.txt",
                    "resource_identity": "dev:1:ino:2",
                    "resource_revision": "size:7:mtime:8",
                    "resource_digest": "a" * 64,
                    "data_class": "public",
                    "trust_level": "trusted_platform",
                }
            },
            upsert=True,
        )
        legacy = store.get_resource_classification(
            workspace_id="workspace-1",
            resource_kind="filesystem",
            resource_ref="storage/generated/fixture.txt",
        )

        observed = resource_classification_for_observation(
            legacy,
            workspace_id="workspace-1",
            resource_kind="filesystem",
            resource_ref="storage/generated/fixture.txt",
            resource_identity="dev:1:ino:2",
            resource_revision="size:7:mtime:8",
            resource_digest="a" * 64,
            provenance="tool_result",
        )

        self.assertEqual(observed.data_class, "unclassified")
        self.assertIsNone(observed.classification_revision)

    def test_legacy_or_malformed_serialization_is_non_authoritative(self) -> None:
        store = self.store()
        assert store.collections.data_attestations is not None
        store.collections.data_attestations.update_one(
            {"workspace_id": "legacy"},
            {"$set": {"workspace_id": "legacy", "declared_remote_data_class": "public"}},
            upsert=True,
        )

        legacy = store.get_data_attestation("legacy")

        self.assertIsNotNone(legacy)
        assert legacy is not None
        self.assertFalse(legacy.authoritative)
        self.assertEqual(legacy.declaration, "legacy_unverified")
        self.assertEqual(attestation_safe_projection(legacy)["state"], "invalid")

        malformed = replace(
            legacy,
            status="active",
            revision="browser-revision",  # type: ignore[arg-type]
            attested_at="browser-time",  # type: ignore[arg-type]
        )
        projection = attestation_safe_projection(malformed)
        self.assertEqual(projection["state"], "invalid")
        self.assertIsNone(projection["revision"])
        self.assertIsNone(projection["attested_at"])

        now = datetime(2026, 8, 26, tzinfo=UTC)
        store.collections.data_attestations.update_one(
            {"workspace_id": "malformed-prefixes"},
            {
                "$set": {
                    "attestation_id": "attestation-malformed-prefixes",
                    "workspace_id": "malformed-prefixes",
                    "declaration": "fake_data_only",
                    "scope_type": "resource_prefixes",
                    "resource_prefixes": "storage/generated",
                    "status": "active",
                    "revision": 1,
                    "attested_by_actor_id": "operator-1",
                    "attested_by_actor_kind": "platform_operator",
                    "attested_at": now,
                    "updated_at": now,
                }
            },
            upsert=True,
        )
        malformed_prefixes = store.get_data_attestation("malformed-prefixes")
        assert malformed_prefixes is not None
        self.assertFalse(malformed_prefixes.authoritative)
        self.assertEqual(
            attestation_safe_projection(malformed_prefixes)["state"],
            "invalid",
        )
        with self.assertRaisesRegex(
            WorkspaceDataGovernanceError,
            "attestation_invalid",
        ):
            store.save_data_attestation(
                malformed_prefixes,
                expected_revision=0,
            )

    def test_invalid_scope_and_naive_timestamp_are_rejected(self) -> None:
        service = WorkspaceDataGovernanceService(self.store())
        for scope_type, prefixes in (
            ("browser", ()),
            ("workspace", ("storage",)),
            ("resource_prefixes", ()),
            ("resource_prefixes", ("../escape",)),
            ("resource_prefixes", ("/absolute/escape",)),
            ("resource_prefixes", ("windows\\escape",)),
        ):
            with self.subTest(scope_type=scope_type, prefixes=prefixes):
                with self.assertRaises(WorkspaceDataGovernanceError):
                    service.issue_attestation(
                        workspace_id="workspace-1",
                        actor_id="operator-1",
                        actor_kind="platform_operator",
                        scope_type=scope_type,
                        resource_prefixes=prefixes,
                        expected_revision=0,
                    )
        with self.assertRaisesRegex(WorkspaceDataGovernanceError, "attestation_timestamp_invalid"):
            service.issue_attestation(
                workspace_id="workspace-1",
                actor_id="operator-1",
                actor_kind="platform_operator",
                scope_type="workspace",
                expected_revision=0,
                now=datetime(2026, 8, 26),
            )


if __name__ == "__main__":
    unittest.main()
