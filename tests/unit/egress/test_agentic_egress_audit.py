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
            destination_provider_id="unlisted-provider",
            destination_upstream_id="unlisted-upstream",
            policy=AgenticEgressPolicy(
                policy_id="full-access-audit",
                revision="1",
                allowed_data_classes=(),
                allowed_provider_ids=(),
                allowed_upstream_ids=(),
                transform_sensitive_text=False,
                audit_only=True,
            ),
        )

        self.assertTrue(result.decision.export_allowed)
        self.assertEqual(result.exported_content, content.encode())
        self.assertEqual(result.decision.reason_code, "egress_audit_only")
        self.assertIsNone(result.decision.transformation)


if __name__ == "__main__":
    unittest.main()
