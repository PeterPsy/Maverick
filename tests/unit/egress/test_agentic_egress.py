from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import unittest

from core.egress import (
    AgenticEgressContentBlock,
    AgenticEgressEvaluator,
    AgenticEgressPolicy,
    public_remote_egress_policy,
)
from core.observability.store import ObservabilityCollections, ObservabilityDocumentStore
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.workspaces.data_governance import (
    issue_fake_data_attestation,
    revoke_data_attestation,
)
from tests.support.collections import FakeCollection


NOW = datetime(2026, 8, 16, tzinfo=UTC)


class AgenticEgressEvaluatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.audit = FakeCollection()
        self.observability = ObservabilityDocumentStore(
            ObservabilityCollections(
                events=FakeCollection(),
                audit=self.audit,
                metrics=FakeCollection(),
            )
        )
        self.decision_store = RuntimeDocumentStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
                egress_decisions=FakeCollection(),
            )
        )
        self.evaluator = AgenticEgressEvaluator(
            digest_key=b"agentic-egress-test-key-value-32b",
            observability_store=self.observability,
            decision_store=self.decision_store,
        )
        self.policy = public_remote_egress_policy(provider_id="fixture-provider")

    def block(self, **updates: object) -> AgenticEgressContentBlock:
        values: dict[str, object] = {
            "content_block_id": "block-1",
            "session_id": "session-1",
            "turn_id": "turn-1",
            "workspace_id": "default",
            "data_class": "public",
            "provenance": "user_input",
            "trust_level": "trusted_actor",
            "content_type": "text/plain",
        }
        values.update(updates)
        return AgenticEgressContentBlock(**values)  # type: ignore[arg-type]

    def test_public_data_is_exported_and_audit_contains_only_hmac_metadata(self) -> None:
        secret_phrase = "public fixture alpha"

        result = self.evaluator.evaluate(
            block=self.block(),
            content=secret_phrase,
            destination_provider_id="fixture-provider",
            destination_upstream_id=None,
            policy=self.policy,
            now=NOW,
        )

        self.assertTrue(result.decision.export_allowed)
        self.assertEqual(result.exported_content, secret_phrase.encode())
        serialized_audit = json.dumps(self.audit.documents, default=str)
        self.assertNotIn(secret_phrase, serialized_audit)
        self.assertNotEqual(
            result.decision.source_digest,
            hashlib.sha256(secret_phrase.encode()).hexdigest(),
        )
        self.assertEqual(
            self.decision_store.list_egress_decisions(session_id="session-1"),
            [result.decision],
        )

    def test_unknown_class_provenance_trust_and_destination_fail_closed(self) -> None:
        scenarios = (
            (self.block(data_class="future_class"), "fixture-provider", "egress_data_class_denied"),
            (self.block(provenance="future_source"), "fixture-provider", "egress_provenance_unknown"),
            (self.block(trust_level="future_trust"), "fixture-provider", "egress_trust_unknown"),
            (self.block(), "other-provider", "egress_destination_denied"),
        )
        for block, provider_id, reason in scenarios:
            with self.subTest(reason=reason):
                result = self.evaluator.evaluate(
                    block=block,
                    content="denied fixture content",
                    destination_provider_id=provider_id,
                    destination_upstream_id=None,
                    policy=self.policy,
                    now=NOW,
                )
                self.assertFalse(result.decision.export_allowed)
                self.assertIsNone(result.exported_content)
                self.assertEqual(result.decision.reason_code, reason)

    def test_fake_class_requires_separate_attestation_and_verified_resource(self) -> None:
        policy = AgenticEgressPolicy(
            policy_id="malformed-fixture-policy",
            revision="1",
            allowed_data_classes=("workspace_internal_fake",),
            allowed_provider_ids=("fixture-provider",),
            allowed_upstream_ids=(),
        )

        result = self.evaluator.evaluate(
            block=self.block(data_class="workspace_internal_fake"),
            content="client-authored classification",
            destination_provider_id="fixture-provider",
            destination_upstream_id=None,
            policy=policy,
            now=NOW,
        )

        self.assertFalse(result.decision.export_allowed)
        self.assertEqual(
            result.decision.reason_code,
            "egress_fake_data_attestation_required",
        )

        attestation = issue_fake_data_attestation(
            workspace_id="default",
            actor_id="operator-1",
            actor_kind="platform_operator",
            scope_type="resource_prefixes",
            resource_prefixes=("storage/generated",),
            expected_revision=0,
            now=NOW,
        )
        unverified = self.evaluator.evaluate(
            block=self.block(data_class="workspace_internal_fake"),
            content="client-authored classification",
            destination_provider_id="fixture-provider",
            destination_upstream_id=None,
            policy=policy,
            data_attestation=attestation,
            now=NOW,
        )
        self.assertFalse(unverified.decision.export_allowed)
        self.assertEqual(
            unverified.decision.reason_code,
            "egress_fake_data_classification_unverified",
        )

        verified_block = self.block(
            content_block_id="block-verified-fake",
            data_class="workspace_internal_fake",
            source_ref="storage/generated/fixture.txt",
            source_revision="size:7:mtime:8",
            resource_identity="dev:1:ino:2",
            classification_revision=1,
        )
        allowed = self.evaluator.evaluate(
            block=verified_block,
            content="server-classified synthetic fixture",
            destination_provider_id="fixture-provider",
            destination_upstream_id=None,
            policy=policy,
            data_attestation=attestation,
            now=NOW,
        )
        self.assertTrue(allowed.decision.export_allowed)

        out_of_scope = self.evaluator.evaluate(
            block=self.block(
                content_block_id="block-out-of-scope",
                data_class="workspace_internal_fake",
                source_ref="workspace-data/records/real.json",
                source_revision="size:7:mtime:8",
                resource_identity="dev:1:ino:3",
                classification_revision=1,
            ),
            content="not covered",
            destination_provider_id="fixture-provider",
            destination_upstream_id=None,
            policy=policy,
            data_attestation=attestation,
            now=NOW,
        )
        self.assertEqual(
            out_of_scope.decision.reason_code,
            "egress_fake_data_attestation_scope_denied",
        )

        revoked = revoke_data_attestation(
            attestation,
            actor_id="operator-2",
            expected_revision=1,
            reason="fixture retired",
            now=NOW,
        )
        denied_after_revocation = self.evaluator.evaluate(
            block=verified_block,
            content="server-classified synthetic fixture",
            destination_provider_id="fixture-provider",
            destination_upstream_id=None,
            policy=policy,
            data_attestation=revoked,
            now=NOW,
        )
        self.assertEqual(
            denied_after_revocation.decision.reason_code,
            "egress_fake_data_attestation_revoked",
        )

    def test_attestation_never_reclassifies_real_or_public_data(self) -> None:
        attestation = issue_fake_data_attestation(
            workspace_id="default",
            actor_id="operator-1",
            actor_kind="platform_operator",
            scope_type="workspace",
            expected_revision=0,
            now=NOW,
        )
        fake_only_policy = AgenticEgressPolicy(
            policy_id="fake-only-policy",
            revision="1",
            allowed_data_classes=("workspace_internal_fake",),
            allowed_provider_ids=("fixture-provider",),
            allowed_upstream_ids=(),
        )
        for data_class in ("public", "workspace_internal", "credential_or_secret", "unclassified"):
            with self.subTest(data_class=data_class):
                result = self.evaluator.evaluate(
                    block=self.block(data_class=data_class),
                    content="classification must remain unchanged",
                    destination_provider_id="fixture-provider",
                    destination_upstream_id=None,
                    policy=fake_only_policy,
                    data_attestation=attestation,
                    now=NOW,
                )
                self.assertFalse(result.decision.export_allowed)
                self.assertEqual(result.decision.data_class, data_class)

    def test_workspace_path_is_rewritten_and_other_host_path_is_denied(self) -> None:
        rewritten = self.evaluator.evaluate(
            block=self.block(),
            content="read /srv/maverick/workspaces/default/generated/report.txt",
            destination_provider_id="fixture-provider",
            destination_upstream_id=None,
            policy=self.policy,
            workspace_root=Path("/srv/maverick/workspaces/default"),
            now=NOW,
        )
        denied = self.evaluator.evaluate(
            block=self.block(content_block_id="block-2"),
            content="read /etc/shadow",
            destination_provider_id="fixture-provider",
            destination_upstream_id=None,
            policy=self.policy,
            now=NOW,
        )

        self.assertEqual(
            rewritten.exported_content,
            b"read workspace://default/generated/report.txt",
        )
        self.assertEqual(rewritten.decision.transformation, "workspace_path_reference")
        self.assertFalse(denied.decision.export_allowed)
        self.assertEqual(denied.decision.reason_code, "egress_host_path_detected")

    def test_tool_result_host_paths_are_redacted_without_weakening_user_input(self) -> None:
        transformed = self.evaluator.evaluate(
            block=self.block(
                provenance="tool_result",
                trust_level="untrusted_tool_output",
                content_type="application/json",
            ),
            content={
                "workspace_file": "/srv/maverick/workspaces/default/AGENTS.md",
                "host_reference": (
                    "The installation root is `/home/ubuntu/projects/maverick-v3`."
                ),
            },
            destination_provider_id="fixture-provider",
            destination_upstream_id=None,
            policy=self.policy,
            workspace_root=Path("/srv/maverick/workspaces/default"),
            now=NOW,
        )
        denied = self.evaluator.evaluate(
            block=self.block(content_block_id="block-user-host-path"),
            content="read /home/ubuntu/.ssh/id_ed25519",
            destination_provider_id="fixture-provider",
            destination_upstream_id=None,
            policy=self.policy,
            now=NOW,
        )

        self.assertTrue(transformed.decision.export_allowed)
        self.assertEqual(
            json.loads(transformed.exported_content or b"{}"),
            {
                "host_reference": (
                    "The installation root is `<redacted-host-path>`."
                ),
                "workspace_file": "workspace://default/AGENTS.md",
            },
        )
        self.assertEqual(
            transformed.decision.transformation,
            "workspace_path_reference+host_path_redaction",
        )
        self.assertFalse(denied.decision.export_allowed)
        self.assertEqual(denied.decision.reason_code, "egress_host_path_detected")

    def test_sensitive_text_is_transformed_but_secret_class_never_exports(self) -> None:
        content = "Authorization: Bearer provider-e2e-secret-never-export"
        transformed = self.evaluator.evaluate(
            block=self.block(),
            content=content,
            destination_provider_id="fixture-provider",
            destination_upstream_id=None,
            policy=self.policy,
            now=NOW,
        )
        denied = self.evaluator.evaluate(
            block=self.block(content_block_id="block-secret", data_class="credential_or_secret"),
            content=content,
            destination_provider_id="fixture-provider",
            destination_upstream_id=None,
            policy=self.policy,
            now=NOW,
        )

        self.assertTrue(transformed.decision.export_allowed)
        self.assertNotIn(b"provider-e2e-secret", transformed.exported_content or b"")
        self.assertEqual(transformed.decision.transformation, "sensitive_text_redaction")
        self.assertFalse(denied.decision.export_allowed)
        serialized_audit = json.dumps(self.audit.documents, default=str)
        self.assertNotIn("provider-e2e-secret", serialized_audit)
        self.assertNotIn("<redacted>", serialized_audit)

    def test_structured_secret_fields_are_redacted_and_retry_is_idempotent(self) -> None:
        block = self.block(content_type="application/json")
        first = self.evaluator.evaluate(
            block=block,
            content={"api_key": "provider-e2e-secret-json", "fixture": True},
            destination_provider_id="fixture-provider",
            destination_upstream_id=None,
            policy=self.policy,
            now=NOW,
        )
        retried = self.evaluator.evaluate(
            block=block,
            content={"fixture": True, "api_key": "provider-e2e-secret-json"},
            destination_provider_id="fixture-provider",
            destination_upstream_id=None,
            policy=self.policy,
            now=NOW.replace(microsecond=1),
        )

        self.assertEqual(first.decision, retried.decision)
        self.assertEqual(
            first.exported_content,
            b'{"api_key":"<redacted>","fixture":true}',
        )
        self.assertEqual(
            len(self.decision_store.list_egress_decisions(session_id="session-1")),
            1,
        )


if __name__ == "__main__":
    unittest.main()
