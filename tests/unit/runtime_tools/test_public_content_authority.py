from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
import unittest

from core.egress.classification import fail_closed_classification
from core.runtime.public_content_authority import (
    RUNTIME_PUBLIC_CONTENT_AUTHORITY_KIND,
    RUNTIME_PUBLIC_CONTENT_AUTHORITY_REF,
)
from core.runtime.public_content_classification import (
    classification_from_runtime_public_content_authority,
    resolve_runtime_public_resource_classification,
)
from core.runtime.public_content_authority_store import (
    issue_runtime_public_content_authority,
    revoke_runtime_public_content_authority,
    runtime_public_content_authority_for_workspace,
    runtime_public_content_authority_record_for_workspace,
)
from core.workspaces.store import WorkspaceCollections, WorkspaceDocumentStore
from tests.support.collections import FakeCollection


NOW = datetime(2026, 8, 31, 15, 0, tzinfo=UTC)
DIGEST = "a" * 64


class RuntimePublicContentAuthorityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = WorkspaceDocumentStore(
            WorkspaceCollections(
                workspaces=FakeCollection(),
                memberships=FakeCollection(),
                governance=FakeCollection(),
                quotas=FakeCollection(),
                active_workspace_selections=FakeCollection(),
                data_attestations=FakeCollection(),
                resource_classifications=FakeCollection(),
                data_governance_audits=FakeCollection(),
            )
        )

    def test_operator_authority_is_explicit_cas_and_revocable(self) -> None:
        issued = issue_runtime_public_content_authority(
            self.store,
            workspace_id="workspace-1",
            actor_id="operator-1",
            expected_revision=0,
            now=NOW,
        )

        self.assertEqual(issued.resource_kind, RUNTIME_PUBLIC_CONTENT_AUTHORITY_KIND)
        self.assertEqual(issued.resource_ref, RUNTIME_PUBLIC_CONTENT_AUTHORITY_REF)
        self.assertEqual(issued.data_class, "public")
        self.assertEqual(
            runtime_public_content_authority_for_workspace(
                self.store,
                "workspace-1",
            ),
            issued,
        )

        revoked = revoke_runtime_public_content_authority(
            self.store,
            workspace_id="workspace-1",
            actor_id="operator-2",
            expected_revision=1,
            reason="workspace is no longer approved for public hosted content",
            now=NOW,
        )

        self.assertEqual(revoked.revision, 2)
        self.assertEqual(revoked.data_class, "unclassified")
        self.assertEqual(revoked.classification_id, issued.classification_id)
        self.assertNotEqual(revoked.resource_digest, issued.resource_digest)
        self.assertIsNone(
            runtime_public_content_authority_for_workspace(
                self.store,
                "workspace-1",
            )
        )
        self.assertEqual(
            runtime_public_content_authority_record_for_workspace(
                self.store,
                "workspace-1",
            ),
            revoked,
        )

    def test_exact_content_binding_is_public_only_while_authority_matches(self) -> None:
        issued = issue_runtime_public_content_authority(
            self.store,
            workspace_id="workspace-1",
            actor_id="operator-1",
            expected_revision=0,
            now=NOW,
        )

        classified = classification_from_runtime_public_content_authority(
            issued,
            workspace_id="workspace-1",
            provenance="user_input",
            trust_level="trusted_actor",
            source_ref="runtime-turn:turn-1:turn-prompt",
            source_revision=DIGEST,
            source_digest=DIGEST,
            resource_identity=f"runtime-input:workspace-1:session-1:turn-1:{DIGEST}",
        )
        mismatched = classification_from_runtime_public_content_authority(
            issued,
            workspace_id="workspace-2",
            provenance="user_input",
            trust_level="trusted_actor",
            source_ref="runtime-turn:turn-1:turn-prompt",
            source_revision=DIGEST,
            source_digest=DIGEST,
            resource_identity=f"runtime-input:workspace-2:session-1:turn-1:{DIGEST}",
        )
        tampered = classification_from_runtime_public_content_authority(
            replace(issued, resource_digest="b" * 64),
            workspace_id="workspace-1",
            provenance="user_input",
            trust_level="trusted_actor",
            source_ref="runtime-turn:turn-1:turn-prompt",
            source_revision=DIGEST,
            source_digest=DIGEST,
            resource_identity=f"runtime-input:workspace-1:session-1:turn-1:{DIGEST}",
        )

        self.assertEqual(classified.data_class, "public")
        self.assertEqual(classified.source_digest, DIGEST)
        self.assertEqual(classified.classification_revision, 1)
        self.assertEqual(mismatched.data_class, "unclassified")
        self.assertEqual(tampered.data_class, "unclassified")

    def test_exact_resource_record_remains_a_restrictive_override(self) -> None:
        issue_runtime_public_content_authority(
            self.store,
            workspace_id="workspace-1",
            actor_id="operator-1",
            expected_revision=0,
            now=NOW,
        )
        observation = SimpleNamespace(
            workspace_id="workspace-1",
            resource_ref="notes.txt",
            resource_revision=DIGEST,
            resource_digest=DIGEST,
            resource_identity="linux:1:2",
        )
        explicit_sensitive = fail_closed_classification(
            provenance="tool_result",
            source_ref="notes.txt",
            source_revision=DIGEST,
            source_digest=DIGEST,
            resource_identity="linux:1:2",
        )
        explicit_sensitive = replace(
            explicit_sensitive,
            data_class="credential_or_secret",
            trust_level="trusted_actor",
            classification_revision=7,
        )

        resolved = resolve_runtime_public_resource_classification(
            self.store,
            observation=observation,
            provenance="tool_result",
            authoritative=explicit_sensitive,
        )

        self.assertEqual(resolved.data_class, "credential_or_secret")
        self.assertEqual(resolved.source_digest, DIGEST)

    def test_exact_resource_record_survives_without_broad_authority(self) -> None:
        observation = SimpleNamespace(
            workspace_id="workspace-1",
            resource_ref="notes.txt",
            resource_revision=DIGEST,
            resource_digest=DIGEST,
            resource_identity="linux:1:2",
        )
        exact_public = replace(
            fail_closed_classification(
                provenance="tool_result",
                source_ref="notes.txt",
                source_revision=DIGEST,
                source_digest=DIGEST,
                resource_identity="linux:1:2",
            ),
            data_class="public",
            trust_level="trusted_actor",
            classification_revision=3,
        )

        resolved = resolve_runtime_public_resource_classification(
            self.store,
            observation=observation,
            provenance="tool_result",
            authoritative=exact_public,
        )

        self.assertEqual(resolved, exact_public)


if __name__ == "__main__":
    unittest.main()
