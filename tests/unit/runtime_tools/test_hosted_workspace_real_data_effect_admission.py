"""Live real-data authority checks around hosted workspace effect commits."""

from __future__ import annotations

from pathlib import Path
import unittest

from core.cli.command_registry import CliCommandRegistry
from core.mcp.tool_registry import McpToolRegistry
from core.runtime.hosted_tool_process_registry import HostedToolProcessRegistry
from core.runtime.hosted_tool_result_admission import (
    build_hosted_tool_result_admission_resolver,
)
from core.runtime.tool_catalog import RuntimeToolActorContext
from core.runtime.tool_core_capabilities import build_core_runtime_tool_capabilities
from core.runtime.tool_errors import RuntimeToolError
from tests.support.hosted_agentic_harness import HostedAgenticHarness


class HostedWorkspaceRealDataEffectAdmissionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = HostedAgenticHarness(self)
        self.workspace = self.harness.root / "workspaces" / "default"
        self.context = RuntimeToolActorContext(
            workspace_id="default",
            actor_id="user-1",
            agent_id="agent-1",
            platform_role="admin",
            workspace_role="admin",
            session_id="session-hosted",
            execution_mode="full-access",
        )

    def test_policy_tightening_rolls_back_an_active_commit(self) -> None:
        full = (
            "public",
            "workspace_internal",
            "personal_data",
            "regulated_or_customer_data",
        )
        current = {"allowed": full}
        resolver = build_hosted_tool_result_admission_resolver(
            cli_registry=CliCommandRegistry(),
            mcp_registry=McpToolRegistry(),
            allowed_remote_data_classes=full,
            live_allowed_remote_data_classes_resolver=lambda: current[
                "allowed"
            ],
        )

        def tighten_after_write(event, path):
            if event == "write_committed" and path == "tightened.txt":
                current["allowed"] = ("public",)

        surfaces = build_core_runtime_tool_capabilities(
            workspace_id="default",
            workspace_root=self.workspace,
            runtime_root=Path(self.harness.session.runtime_root),
            process_registry=HostedToolProcessRegistry(store=self.harness.store),
            result_classification_resolver=resolver,
            filesystem_race_hook=tighten_after_write,
        )
        capabilities = {
            surface.definition.handle: surface for surface in surfaces
        }
        instructions = capabilities[
            "core-capability:workspace.instructions"
        ].handler(
            {"path": ".", "target_is_directory": True},
            self.context,
            None,
        )
        with self.assertRaisesRegex(
            RuntimeToolError,
            "tool_result_egress_not_guaranteed",
        ):
            capabilities["core-capability:shell.run"].handler(
                {
                    "argv": [
                        "/bin/sh",
                        "-c",
                        "printf blocked > tightened.txt; printf ordinary",
                    ],
                    "mutation_scopes": [
                        {
                            "path": ".",
                            "instruction_scope_digest": instructions.payload[
                                "scope_digest"
                            ],
                        }
                    ],
                },
                self.context,
                None,
            )
        self.assertFalse((self.workspace / "tightened.txt").exists())


if __name__ == "__main__":
    unittest.main()
