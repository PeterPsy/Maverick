from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from core.cli.command_registry import CliCommandRegistry
from core.cli.models import CliCommandDefinition, CliInvocationPolicy
from core.mcp.models import McpInvocationPolicy, McpToolDefinition
from core.mcp.tool_registry import McpToolRegistry
from core.runtime.process_control import runtime_processes_alive_for_session
from core.runtime.tool_errors import RuntimeToolError
from core.runtime.confined_filesystem import ConfinedWorkspaceFilesystem
from core.runtime.hosted_workspace_snapshot import HostedWorkspaceSnapshot
from tests.support.cases.full_workspace_contract import FullWorkspaceContractFixture


class FullWorkspaceLimitsAndDiscoveryTest(FullWorkspaceContractFixture, unittest.TestCase):
    def test_workspace_snapshot_is_bounded_and_excludes_git_symlinks(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            runtime_root = root / "runtime"
            runtime_root.mkdir()
            (root / "one").write_text("one", encoding="utf-8")
            (root / "two").write_text("two", encoding="utf-8")
            filesystem = ConfinedWorkspaceFilesystem(
                workspace_id="snapshot-test",
                workspace_root=root,
            )
            self.addCleanup(filesystem.close)
            with patch(
                "core.runtime.hosted_workspace_snapshot."
                "MAX_HOSTED_WORKSPACE_SNAPSHOT_ENTRIES",
                1,
            ):
                with self.assertRaisesRegex(
                    RuntimeToolError,
                    "workspace_snapshot_too_large",
                ):
                    HostedWorkspaceSnapshot.create(
                        filesystem,
                        runtime_root=runtime_root,
                    )

            (root / "one").unlink()
            (root / "two").unlink()
            (root / "private").mkdir()
            (root / ".git").symlink_to(root / "private", target_is_directory=True)
            snapshot = HostedWorkspaceSnapshot.create(
                filesystem,
                runtime_root=runtime_root,
            )
            try:
                snapshot_fd = snapshot.duplicate_root_fd()
                with self.assertRaises(FileNotFoundError):
                    os.stat(".git", dir_fd=snapshot_fd, follow_symlinks=False)
            finally:
                os.close(snapshot_fd)
                snapshot.discard()

    def test_shell_masks_git_worktree_pointer_file(self) -> None:
        (self.workspace / ".git").write_text(
            "gitdir: /platform/private/worktree\n",
            encoding="utf-8",
        )
        shell = self._capabilities()["core-capability:shell.run"].handler(
            {
                "argv": [
                    "/bin/sh",
                    "-c",
                    "test ! -s /workspace/.git && printf masked",
                ],
                "mutation_scopes": [],
            },
            self.context,
            None,
        )

        self.assertEqual(shell["output"], "masked")

    def test_shell_and_process_output_and_time_are_hard_bounded(self) -> None:
        capabilities = self._capabilities(processes=True)
        with self.assertRaisesRegex(RuntimeToolError, "shell_output_too_large"):
            capabilities["core-capability:shell.run"].handler(
                {
                    "argv": ["/usr/bin/head", "-c", "200000", "/dev/zero"],
                    "mutation_scopes": [],
                },
                self.context,
                None,
            )

        with patch("core.runtime.hosted_process_output.MAX_PROCESS_OUTPUT_BYTES", 64):
            overflowing = capabilities["core-capability:process.start"].handler(
                {
                    "argv": ["/usr/bin/head", "-c", "1024", "/dev/zero"],
                    "timeout_seconds": 5,
                    "mutation_scopes": [],
                },
                self.context,
                None,
            )
            overflow_status = self._wait_for_process(
                capabilities,
                str(overflowing.payload["process_id"]),
            )
        self.assertEqual(overflow_status.payload["status"], "failed")
        self.assertEqual(
            overflow_status.payload["failure_reason"],
            "process_output_too_large",
        )
        self.assertTrue(overflow_status.payload["output_truncated"])

        timing_out = capabilities["core-capability:process.start"].handler(
            {
                "argv": ["/bin/sh", "-c", "sleep 10"],
                "timeout_seconds": 1,
                "mutation_scopes": [],
            },
            self.context,
            None,
        )
        timeout_status = self._wait_for_process(
            capabilities,
            str(timing_out.payload["process_id"]),
        )
        self.assertEqual(timeout_status.payload["status"], "timed-out")
        self.assertEqual(
            timeout_status.payload["failure_reason"],
            "process_timed_out",
        )
        self.assertFalse(runtime_processes_alive_for_session("session-hosted"))

    def test_cli_and_mcp_require_discovery_token_across_catalog_refresh(self) -> None:
        cli = CliCommandRegistry()
        cli.register_command(
            CliCommandDefinition(
                command_id="fixture.echo",
                path_segments=["fixture", "echo"],
                description="Echo a fixture.",
                argument_schema={"type": "object"},
                owner_kind="core",
                owner_id="core",
                workspace_id=None,
                exposure_scope="core_global",
                invocation_policy=CliInvocationPolicy(
                    operator_only=False,
                    required_platform_role=None,
                    sandbox_agent_allowed=True,
                    requires_workspace_context=True,
                    requires_full_access=False,
                ),
                entrypoint_path=None,
                effect_class="read",
                safe_to_retry=True,
                schema_public=True,
                certified_tcb_component="tool-schema-catalog",
            ),
            lambda arguments, _context: {"echo": arguments.get("value")},
        )
        mcp = McpToolRegistry()
        mcp.register_tool(
            McpToolDefinition(
                tool_name="fixture_lookup",
                description="Lookup a fixture.",
                input_schema={"type": "object"},
                output_schema=None,
                owner_kind="core",
                owner_id="core",
                workspace_id=None,
                exposure_scope="core_global",
                invocation_policy=McpInvocationPolicy(
                    operator_only=False,
                    sandbox_agent_allowed=True,
                    requires_workspace_context=True,
                    requires_full_access=False,
                ),
                entrypoint_path=None,
                effect_class="read",
                safe_to_retry=True,
                schema_public=True,
                certified_tcb_component="tool-schema-catalog",
            ),
            lambda arguments, _context: {"found": arguments.get("id")},
        )
        first = self._discovery(cli, mcp)
        cli_listing = first["core-capability:cli.list"].handler(
            {}, self.context, None
        )
        mcp_listing = first["core-capability:mcp.list"].handler(
            {}, self.context, None
        )

        refreshed = self._discovery(cli, mcp)
        cli_result = refreshed["core-capability:cli.run"].handler(
            {
                "command_id": "fixture.echo",
                "invocation_token": cli_listing.payload["commands"][0][
                    "invocation_token"
                ],
                "arguments": {"value": "ok"},
            },
            self.context,
            None,
        )
        mcp_result = refreshed["core-capability:mcp.call"].handler(
            {
                "tool_name": "fixture_lookup",
                "invocation_token": mcp_listing.payload["tools"][0][
                    "invocation_token"
                ],
                "arguments": {"id": 7},
            },
            self.context,
            None,
        )
        self.assertEqual(cli_result.payload, {"echo": "ok"})
        self.assertEqual(mcp_result.payload, {"found": 7})
        with self.assertRaisesRegex(RuntimeToolError, "tool_discovery_required"):
            refreshed["core-capability:cli.run"].handler(
                {
                    "command_id": "fixture.echo",
                    "arguments": {},
                },
                self.context,
                None,
            )


if __name__ == "__main__":
    unittest.main()
