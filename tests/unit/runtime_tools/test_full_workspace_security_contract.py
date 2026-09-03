from __future__ import annotations

import unittest

from core.runtime.full_workspace_contract import (
    FULL_WORKSPACE_CONTRACT_REVISION,
    FULL_WORKSPACE_REQUIRED_RESULT_BEHAVIORS,
)


class FullWorkspaceSecurityContractTest(unittest.TestCase):
    def test_v18_requires_executable_process_and_boundary_probes(self) -> None:
        self.assertEqual(FULL_WORKSPACE_CONTRACT_REVISION, "codex-baseline-v18")
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
