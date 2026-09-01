from __future__ import annotations

import os
import stat
import unittest

from core.runtime.tool_errors import RuntimeToolError
from tests.support.cases.full_workspace_contract import FullWorkspaceContractFixture


class FullWorkspaceInstructionScopeContractTest(FullWorkspaceContractFixture, unittest.TestCase):
    def test_shell_and_process_commit_only_declared_nested_instruction_scopes(self) -> None:
        nested = self.workspace / "nested"
        nested.mkdir()
        (self.workspace / "AGENTS.md").write_text("Root rules.\n", encoding="utf-8")
        (nested / "AGENTS.md").write_text("Nested rules.\n", encoding="utf-8")
        metadata_file = nested / "metadata.txt"
        metadata_file.write_text("unchanged", encoding="utf-8")
        capabilities = self._capabilities(processes=True)
        root_digest = self._scope_digest(
            capabilities,
            ".",
            target_is_directory=True,
        )
        nested_digest = self._scope_digest(
            capabilities,
            "nested",
            target_is_directory=True,
        )

        with self.assertRaisesRegex(
            RuntimeToolError,
            "workspace_instruction_scope_changed",
        ):
            capabilities["core-capability:shell.run"].handler(
                {
                    "argv": [
                        "/bin/sh",
                        "-c",
                        "printf blocked > nested/shell-blocked.txt",
                    ],
                    "mutation_scopes": [
                        {
                            "path": ".",
                            "instruction_scope_digest": root_digest,
                        }
                    ],
                },
                self.context,
                None,
            )
        self.assertFalse((nested / "shell-blocked.txt").exists())

        with self.assertRaisesRegex(
            RuntimeToolError,
            "workspace_effect_outside_declared_scope",
        ):
            capabilities["core-capability:shell.run"].handler(
                {
                    "argv": [
                        "/bin/sh",
                        "-c",
                        "printf blocked > outside-declared-scope.txt",
                    ],
                    "mutation_scopes": [
                        {
                            "path": "nested",
                            "instruction_scope_digest": nested_digest,
                        }
                    ],
                },
                self.context,
                None,
            )
        self.assertFalse((self.workspace / "outside-declared-scope.txt").exists())

        overlay_fd_bypass = capabilities["core-capability:shell.run"].handler(
            {
                "argv": [
                    "/usr/bin/python3",
                    "-c",
                    (
                        "import os\n"
                        "for fd in range(3,128):\n"
                        " try:\n"
                        "  handle=os.open('overlay-descriptor-bypass.txt',"
                        "os.O_WRONLY|os.O_CREAT,0o600,dir_fd=fd)\n"
                        "  os.write(handle,b'bypass'); os.close(handle)\n"
                        " except OSError: pass\n"
                    ),
                ],
                "mutation_scopes": [
                    {
                        "path": "nested",
                        "instruction_scope_digest": nested_digest,
                    }
                ],
            },
            self.context,
            None,
        )
        self.assertEqual(overlay_fd_bypass["exit_code"], 0)
        self.assertFalse(
            (self.workspace / "overlay-descriptor-bypass.txt").exists()
        )

        with self.assertRaisesRegex(
            RuntimeToolError,
            "workspace_effect_directory_unsupported",
        ):
            capabilities["core-capability:shell.run"].handler(
                {
                    "argv": [
                        "/bin/sh",
                        "-c",
                        "mkdir -p nested/new && printf blocked > nested/new/file.txt",
                    ],
                    "mutation_scopes": [
                        {
                            "path": "nested",
                            "instruction_scope_digest": nested_digest,
                        }
                    ],
                },
                self.context,
                None,
            )
        self.assertFalse((nested / "new").exists())

        with self.assertRaisesRegex(
            RuntimeToolError,
            "workspace_effect_directory_unsupported",
        ):
            capabilities["core-capability:shell.run"].handler(
                {
                    "argv": ["/bin/mkdir", "nested/empty-directory"],
                    "mutation_scopes": [
                        {
                            "path": "nested",
                            "instruction_scope_digest": nested_digest,
                        }
                    ],
                },
                self.context,
                None,
            )
        self.assertFalse((nested / "empty-directory").exists())

        with self.assertRaisesRegex(
            RuntimeToolError,
            "workspace_effect_metadata_unsupported",
        ):
            capabilities["core-capability:shell.run"].handler(
                {
                    "argv": ["/bin/chmod", "700", "nested"],
                    "mutation_scopes": [
                        {
                            "path": "nested",
                            "instruction_scope_digest": nested_digest,
                        }
                    ],
                },
                self.context,
                None,
            )

        with self.assertRaisesRegex(
            RuntimeToolError,
            "workspace_effect_metadata_unsupported",
        ):
            capabilities["core-capability:shell.run"].handler(
                {
                    "argv": ["/bin/chmod", "700", "nested/metadata.txt"],
                    "mutation_scopes": [
                        {
                            "path": "nested",
                            "instruction_scope_digest": nested_digest,
                        }
                    ],
                },
                self.context,
                None,
            )
        self.assertEqual(metadata_file.read_text(encoding="utf-8"), "unchanged")

        with self.assertRaisesRegex(
            RuntimeToolError,
            "workspace_effect_metadata_unsupported",
        ):
            capabilities["core-capability:shell.run"].handler(
                {
                    "argv": [
                        "/usr/bin/python3",
                        "-c",
                        (
                            "import os; "
                            "os.setxattr('nested/metadata.txt', "
                            "b'user.maverick.effect', b'ignored')"
                        ),
                    ],
                    "mutation_scopes": [
                        {
                            "path": "nested",
                            "instruction_scope_digest": nested_digest,
                        }
                    ],
                },
                self.context,
                None,
            )
        with self.assertRaises(OSError):
            os.getxattr(metadata_file, "user.maverick.effect")

        original_mtime_ns = metadata_file.stat().st_mtime_ns
        with self.assertRaisesRegex(
            RuntimeToolError,
            "workspace_effect_metadata_unsupported",
        ):
            capabilities["core-capability:shell.run"].handler(
                {
                    "argv": [
                        "/bin/touch",
                        "-t",
                        "200001010000",
                        "nested/metadata.txt",
                    ],
                    "mutation_scopes": [
                        {
                            "path": "nested",
                            "instruction_scope_digest": nested_digest,
                        }
                    ],
                },
                self.context,
                None,
            )
        self.assertEqual(metadata_file.stat().st_mtime_ns, original_mtime_ns)

        self.workspace.chmod(0o755)
        root_digest = self._scope_digest(
            capabilities,
            ".",
            target_is_directory=True,
        )
        with self.assertRaisesRegex(
            RuntimeToolError,
            "workspace_effect_metadata_unsupported",
        ):
            capabilities["core-capability:shell.run"].handler(
                {
                    "argv": ["/bin/chmod", "700", "."],
                    "mutation_scopes": [
                        {
                            "path": ".",
                            "instruction_scope_digest": root_digest,
                        }
                    ],
                },
                self.context,
                None,
            )
        self.assertEqual(stat.S_IMODE(self.workspace.stat().st_mode), 0o755)

        shell = capabilities["core-capability:shell.run"].handler(
            {
                "argv": [
                    "/bin/sh",
                    "-c",
                    "printf allowed > nested/shell-allowed.txt",
                ],
                "mutation_scopes": [
                    {
                        "path": "nested",
                        "instruction_scope_digest": nested_digest,
                    }
                ],
            },
            self.context,
            None,
        )
        self.assertEqual(shell["workspace_effect_paths"], ("nested/shell-allowed.txt",))
        self.assertEqual(
            (nested / "shell-allowed.txt").read_text(encoding="utf-8"),
            "allowed",
        )

        blocked = capabilities["core-capability:process.start"].handler(
            {
                "argv": [
                    "/bin/sh",
                    "-c",
                    "printf blocked > nested/process-blocked.txt",
                ],
                "mutation_scopes": [
                    {
                        "path": ".",
                        "instruction_scope_digest": root_digest,
                    }
                ],
            },
            self.context,
            None,
        )
        with self.assertRaisesRegex(
            RuntimeToolError,
            "workspace_instruction_scope_changed",
        ):
            self._wait_for_process(
                capabilities,
                str(blocked.payload["process_id"]),
            )
        blocked_record = self.harness.store.get_process(
            str(blocked.payload["process_id"])
        )
        self.assertEqual(blocked_record.status, "failed")
        self.assertEqual(
            blocked_record.failure_reason,
            "workspace_instruction_scope_changed",
        )
        self.assertFalse((nested / "process-blocked.txt").exists())

        allowed = capabilities["core-capability:process.start"].handler(
            {
                "argv": [
                    "/bin/sh",
                    "-c",
                    "printf allowed > nested/process-allowed.txt",
                ],
                "mutation_scopes": [
                    {
                        "path": "nested",
                        "instruction_scope_digest": nested_digest,
                    }
                ],
            },
            self.context,
            None,
        )
        allowed_status = self._wait_for_process(
            capabilities,
            str(allowed.payload["process_id"]),
        )
        self.assertEqual(allowed_status.payload["status"], "exited")
        self.assertTrue(
            allowed_status.payload["workspace_effects"][
                "workspace_effects_committed"
            ]
        )
        self.assertEqual(
            (nested / "process-allowed.txt").read_text(encoding="utf-8"),
            "allowed",
        )


if __name__ == "__main__":
    unittest.main()
