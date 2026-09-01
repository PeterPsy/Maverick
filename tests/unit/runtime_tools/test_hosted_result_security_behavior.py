from __future__ import annotations

import unittest
from unittest.mock import patch

from core.runtime.confined_filesystem import ConfinedWorkspaceFilesystem
from core.runtime.hosted_agentic_request import HostedAgenticRequestBuilder
from core.runtime.hosted_result_authority_guard import HostedResultAuthorityGuard
from core.runtime.hosted_result_security_behavior import (
    HOSTED_RESULT_SECURITY_BEHAVIOR_IDS,
    inspect_hosted_result_security_behavior,
)


class HostedResultSecurityBehaviorTest(unittest.TestCase):
    def setUp(self) -> None:
        inspect_hosted_result_security_behavior.cache_clear()
        self.addCleanup(inspect_hosted_result_security_behavior.cache_clear)

    def test_all_negative_security_probes_execute(self) -> None:
        self.assertEqual(
            inspect_hosted_result_security_behavior(),
            HOSTED_RESULT_SECURITY_BEHAVIOR_IDS,
        )

    def test_marker_gate_depends_on_complete_raw_resource_scan(self) -> None:
        def chunk_only_classification(filesystem, _fd, _observed, observation):
            return filesystem._classification(observation, "tool_result")

        with patch.object(
            ConfinedWorkspaceFilesystem,
            "_classification_for_complete_file",
            chunk_only_classification,
        ):
            verified = inspect_hosted_result_security_behavior()

        self.assertNotIn("security:filesystem.marker-narrowing", verified)

    def test_transport_gate_depends_on_last_boundary_revalidation(self) -> None:
        with patch.object(
            HostedAgenticRequestBuilder,
            "revalidate_for_transport",
            return_value=None,
        ):
            verified = inspect_hosted_result_security_behavior()

        self.assertNotIn("security:request.revoke-transport", verified)

    def test_overlay_gate_depends_on_post_commit_authority_guard(self) -> None:
        with patch.object(
            HostedResultAuthorityGuard,
            "_verify",
            return_value=None,
        ):
            verified = inspect_hosted_result_security_behavior()

        self.assertNotIn("security:workspace-effect.revoke-commit", verified)


if __name__ == "__main__":
    unittest.main()
