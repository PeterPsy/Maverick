from __future__ import annotations

import unittest

from core.runtime.full_workspace_contract import (
    FULL_WORKSPACE_CONTRACT_REVISION,
    FULL_WORKSPACE_REQUIRED_RESULT_BEHAVIORS,
)


class FullWorkspaceSecurityContractTest(unittest.TestCase):
    def test_v13_requires_product_boundary_revocation_probes(self) -> None:
        self.assertEqual(FULL_WORKSPACE_CONTRACT_REVISION, "codex-baseline-v13")
        self.assertEqual(len(FULL_WORKSPACE_REQUIRED_RESULT_BEHAVIORS), 18)
        self.assertTrue(
            {
                "security:filesystem.marker-narrowing",
                "security:filesystem.revoke-rebuild",
                "security:tool-result.revoke-egress",
                "security:request.revoke-transport",
                "security:workspace-effect.revoke-commit",
            }.issubset(FULL_WORKSPACE_REQUIRED_RESULT_BEHAVIORS)
        )


if __name__ == "__main__":
    unittest.main()
