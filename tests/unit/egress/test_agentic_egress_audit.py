from __future__ import annotations

import unittest

from core.egress import (
    AgenticEgressContentBlock,
    AgenticEgressEvaluator,
    AgenticEgressPolicy,
)


class AgenticEgressAuditTest(unittest.TestCase):
    def test_audit_only_policy_preserves_content_without_filtering(self) -> None:
        content = "read /home/ubuntu/.ssh/id_ed25519"
        result = AgenticEgressEvaluator(
            digest_key=b"full-access-audit-test-key-value"
        ).evaluate(
            block=AgenticEgressContentBlock(
                content_block_id="block-1",
                session_id="session-1",
                turn_id="turn-1",
                workspace_id="default",
                data_class="workspace_internal",
                provenance="user_input",
                trust_level="trusted_actor",
                content_type="text/plain",
            ),
            content=content,
            destination_provider_id="selected-provider",
            destination_upstream_id="selected-upstream",
            policy=AgenticEgressPolicy(
                policy_id="full-access-audit",
                revision="1",
                allowed_data_classes=(),
                allowed_provider_ids=("selected-provider",),
                allowed_upstream_ids=("selected-upstream",),
                transform_sensitive_text=False,
                audit_only=True,
            ),
        )

        self.assertTrue(result.decision.export_allowed)
        self.assertEqual(result.exported_content, content.encode())
        self.assertEqual(result.decision.reason_code, "egress_audit_only")
        self.assertIsNone(result.decision.transformation)

    def test_audit_only_policy_still_enforces_transport_routing(self) -> None:
        evaluator = AgenticEgressEvaluator(
            digest_key=b"full-access-audit-test-key-value"
        )
        block = AgenticEgressContentBlock(
            content_block_id="block-1",
            session_id="session-1",
            turn_id="turn-1",
            workspace_id="default",
            data_class="credential_or_secret",
            provenance="user_input",
            trust_level="trusted_actor",
            content_type="text/plain",
        )
        policy = AgenticEgressPolicy(
            policy_id="full-access-audit",
            revision="1",
            allowed_data_classes=(),
            allowed_provider_ids=("selected-provider",),
            allowed_upstream_ids=("selected-upstream",),
            transform_sensitive_text=False,
            audit_only=True,
        )

        wrong_provider = evaluator.evaluate(
            block=block,
            content="secret",
            destination_provider_id="different-provider",
            destination_upstream_id="selected-upstream",
            policy=policy,
        )
        wrong_upstream = evaluator.evaluate(
            block=block,
            content="secret",
            destination_provider_id="selected-provider",
            destination_upstream_id="different-upstream",
            policy=policy,
        )

        self.assertFalse(wrong_provider.decision.export_allowed)
        self.assertEqual(
            wrong_provider.decision.reason_code,
            "egress_destination_denied",
        )
        self.assertIsNone(wrong_provider.exported_content)
        self.assertFalse(wrong_upstream.decision.export_allowed)
        self.assertEqual(wrong_upstream.decision.reason_code, "egress_upstream_denied")
        self.assertIsNone(wrong_upstream.exported_content)


if __name__ == "__main__":
    unittest.main()
