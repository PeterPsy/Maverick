"""Security-boundary tests for canonical source classification and taint."""

from __future__ import annotations

from dataclasses import replace
import unittest

from core.egress.classification import (
    content_sha256,
    join_classifications,
    validated_classification,
)
from core.workspaces.data_governance import (
    WorkspaceResourceClassification,
    resource_classification_for_observation,
)
from datetime import UTC, datetime


class CanonicalClassificationTestCase(unittest.TestCase):
    def source(self, data_class: str, *, provenance: str = "user_input", trust: str = "trusted_actor"):
        content = f"{data_class}:{provenance}".encode()
        return validated_classification(
            data_class=data_class,
            provenance=provenance,
            trust_level=trust,
            source_ref=f"source/{provenance}",
            source_revision="version-1",
            source_digest=content_sha256(content),
            resource_identity="dev:1:ino:2",
            classification_revision=1,
        )

    def test_join_is_monotonic_and_empty_or_invalid_sources_fail_closed(self) -> None:
        joined = join_classifications(
            (
                self.source("public", provenance="platform_instruction", trust="trusted_platform"),
                self.source("personal_data"),
                self.source("workspace_internal_fake", provenance="attachment", trust="untrusted_external"),
            )
        )

        self.assertEqual(joined.effective_data_class, "personal_data")
        self.assertEqual(joined.effective_trust_level, "untrusted_external")
        self.assertEqual(join_classifications(()).effective_data_class, "unclassified")
        malformed = replace(self.source("public"), source_revision="")
        self.assertEqual(join_classifications((malformed,)).effective_data_class, "unclassified")

    def test_fake_labels_policy_ids_and_client_claims_cannot_reclassify_a_resource(self) -> None:
        now = datetime(2026, 8, 26, tzinfo=UTC)
        content = b"actual customer record"
        actual = WorkspaceResourceClassification(
            classification_id="classification-1",
            workspace_id="workspace-1",
            resource_kind="filesystem_file",
            resource_ref="storage/customer.txt",
            resource_identity="dev:1:ino:2",
            resource_revision="version-1",
            resource_digest=content_sha256(content),
            data_class="regulated_or_customer_data",
            trust_level="trusted_actor",
            revision=4,
            classified_by_actor_id="operator-1",
            classified_at=now,
            updated_at=now,
        )

        resolved = resource_classification_for_observation(
            actual,
            workspace_id="workspace-1",
            resource_kind="filesystem_file",
            resource_ref="storage/customer.txt",
            resource_identity="dev:1:ino:2",
            resource_revision="version-1",
            resource_digest=content_sha256(content),
            provenance="tool_result",
        )

        # No declaration, egress policy id, UI label, or caller data-class is an
        # argument to this resolver.  Only the observed resource record wins.
        self.assertEqual(resolved.data_class, "regulated_or_customer_data")
        self.assertEqual(resolved.classification_revision, 4)

    def test_missing_or_incoherent_resource_revision_is_unclassified(self) -> None:
        content = b"one"
        now = datetime(2026, 8, 26, tzinfo=UTC)
        record = WorkspaceResourceClassification(
            classification_id="classification-1",
            workspace_id="workspace-1",
            resource_kind="filesystem_file",
            resource_ref="storage/file.txt",
            resource_identity="dev:1:ino:2",
            resource_revision="version-1",
            resource_digest=content_sha256(content),
            data_class="public",
            trust_level="trusted_actor",
            revision=1,
            classified_by_actor_id="operator-1",
            classified_at=now,
            updated_at=now,
        )

        for classification, revision, digest in (
            (None, "version-1", content_sha256(content)),
            (record, "version-2", content_sha256(content)),
            (record, "version-1", content_sha256(b"two")),
        ):
            with self.subTest(revision=revision, digest=digest):
                resolved = resource_classification_for_observation(
                    classification,
                    workspace_id="workspace-1",
                    resource_kind="filesystem_file",
                    resource_ref="storage/file.txt",
                    resource_identity="dev:1:ino:2",
                    resource_revision=revision,
                    resource_digest=digest,
                    provenance="tool_result",
                )
                self.assertEqual(resolved.data_class, "unclassified")

    def test_unknown_provenance_or_trust_fails_closed(self) -> None:
        source = validated_classification(
            data_class="public",
            provenance="browser_claim",
            trust_level="browser_trusted",
            source_ref="claimed",
            source_revision="one",
            source_digest=content_sha256(b"claimed"),
            resource_identity="claimed",
            classification_revision=1,
        )

        self.assertEqual(source.data_class, "unclassified")
        self.assertEqual(source.provenance, "tool_result")
        self.assertEqual(source.trust_level, "untrusted_external")


if __name__ == "__main__":
    unittest.main()
