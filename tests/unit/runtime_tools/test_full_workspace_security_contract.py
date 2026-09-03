from __future__ import annotations

import unittest

from core.runtime.full_workspace_contract import (
    FULL_WORKSPACE_CONTRACT_REVISION,
    FULL_WORKSPACE_REQUIRED_RESULT_BEHAVIORS,
)
from core.runtime.hosted_tool_result_behavior import (
    HOSTED_TOOL_RESULT_BEHAVIOR_REVISION,
)


class FullWorkspaceSecurityContractTest(unittest.TestCase):
    def test_v20_requires_semantic_and_budget_complete_policy_fencing(self) -> None:
        self.assertEqual(FULL_WORKSPACE_CONTRACT_REVISION, "codex-baseline-v20")
        self.assertEqual(HOSTED_TOOL_RESULT_BEHAVIOR_REVISION, 10)
        self.assertEqual(len(FULL_WORKSPACE_REQUIRED_RESULT_BEHAVIORS), 24)
        self.assertTrue(
            {
                "security:filesystem.marker-narrowing",
                "security:filesystem.revoke-rebuild",
                "security:tool-result.revoke-egress",
                "security:request.revoke-transport",
                "security:stream.revoke-advance",
                "security:workspace-effect.revoke-commit",
                "security:workspace.git-masked",
                "collaboration:cli-create-mcp-wait",
                "core-capability:process.start",
                "core-capability:process.status",
                "core-capability:process.input",
                "core-capability:process.interrupt",
            }.issubset(FULL_WORKSPACE_REQUIRED_RESULT_BEHAVIORS)
        )


if __name__ == "__main__":
    unittest.main()
