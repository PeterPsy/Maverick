from __future__ import annotations

import unittest

from core.runtime.full_workspace_contract import (
    FULL_WORKSPACE_CONTRACT_REVISION,
    FULL_WORKSPACE_REQUIRED_RESULT_BEHAVIORS,
)


class FullWorkspaceSecurityContractTest(unittest.TestCase):
    def test_v16_requires_product_boundary_and_collaboration_probes(self) -> None:
        self.assertEqual(FULL_WORKSPACE_CONTRACT_REVISION, "codex-baseline-v16")
        self.assertEqual(len(FULL_WORKSPACE_REQUIRED_RESULT_BEHAVIORS), 21)
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
            }.issubset(FULL_WORKSPACE_REQUIRED_RESULT_BEHAVIORS)
        )


if __name__ == "__main__":
    unittest.main()
