from __future__ import annotations

from types import SimpleNamespace
import unittest

from core.runtime.full_workspace_contract import (
    FULL_WORKSPACE_REQUIRED_RESULT_MODES,
    inspect_full_workspace_contract,
)
from core.runtime.hosted_tool_result_admission import HOSTED_TOOL_RESULT_MODES


class FullWorkspaceResultContractTest(unittest.TestCase):
    def test_complete_contract_requires_semantically_complete_result_modes(
        self,
    ) -> None:
        capabilities = SimpleNamespace(
            streaming=True,
            tool_orchestration=True,
            cli=True,
            mcp=True,
            skill_catalog=True,
            filesystem_list=True,
            filesystem_read=True,
            filesystem_write=True,
            shell=True,
            interrupt=True,
            recovery=True,
            confirmation_resume=True,
            app_references=True,
            confirmations=True,
            attachment_modalities=("file",),
        )
        policy = SimpleNamespace(
            require_confirmation_for_mutating=True,
            require_confirmation_for_destructive=True,
            allowed_surface_kinds=("core-capability",),
            tool_handle_mode="all_currently_authorized",
            allowed_tool_handles=(),
        )

        complete = inspect_full_workspace_contract(
            capabilities=capabilities,
            policy=policy,
            tool_result_modes=HOSTED_TOOL_RESULT_MODES,
        )
        self.assertTrue(complete.complete)
        self.assertEqual(
            set(FULL_WORKSPACE_REQUIRED_RESULT_MODES),
            set(HOSTED_TOOL_RESULT_MODES),
        )

        partial_result_modes = dict(HOSTED_TOOL_RESULT_MODES)
        partial_result_modes["core-capability:shell.run"] = (
            "public_acknowledgement"
        )
        partial = inspect_full_workspace_contract(
            capabilities=capabilities,
            policy=policy,
            tool_result_modes=partial_result_modes,
        )
        self.assertFalse(partial.complete)
        self.assertEqual(
            partial.missing_result_modes,
            ("core-capability:shell.run",),
        )


if __name__ == "__main__":
    unittest.main()
