from __future__ import annotations

import os
import time
import unittest

from core.runtime.tool_errors import RuntimeToolError
from tests.support.cases.full_workspace_contract import FullWorkspaceContractFixture


class FullWorkspaceMutationContractTest(FullWorkspaceContractFixture, unittest.TestCase):
    def test_shell_overlay_materializes_file_times_and_rejects_root_atime(self) -> None:
        (self.workspace / "AGENTS.md").write_text(
            "Timestamp rules.\n",
            encoding="utf-8",
        )
        target = self.workspace / "timestamp.txt"
        target.write_text("old", encoding="utf-8")
        requested_mtime_ns = time.time_ns() + 1_500_000_000
        capabilities = self._capabilities()
        scope_digest = self._scope_digest(
            capabilities,
            ".",
            target_is_directory=True,
        )

        result = capabilities["core-capability:shell.run"].handler(
            {
                "argv": [
                    "/usr/bin/python3",
                    "-c",
                    (
                        "import os; "
                        "p='timestamp.txt'; "
                        "open(p, 'w', encoding='utf-8').write('new'); "
                        "s=os.stat(p); "
                        f"os.utime(p, ns=(s.st_atime_ns, {requested_mtime_ns}))"
                    ),
                ],
                "mutation_scopes": [
                    {
                        "path": ".",
                        "instruction_scope_digest": scope_digest,
                    }
                ],
            },
            self.context,
            None,
        )
        self.assertTrue(result["workspace_effects_committed"])
        self.assertEqual(target.read_text(encoding="utf-8"), "new")
        self.assertEqual(target.stat().st_mtime_ns, requested_mtime_ns)

        requested_root_atime_ns = 946_684_800_000_000_000
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
                            "import os; s=os.stat('.'); "
                            f"os.utime('.', ns=({requested_root_atime_ns}, "
                            "s.st_mtime_ns))"
                        ),
                    ],
                    "mutation_scopes": [
                        {
                            "path": ".",
                            "instruction_scope_digest": scope_digest,
                        }
                    ],
                },
                self.context,
                None,
            )
        self.assertNotEqual(
            self.workspace.stat().st_atime_ns,
            requested_root_atime_ns,
        )

    def test_shell_overlay_rejects_new_and_existing_hardlinks(self) -> None:
        (self.workspace / "AGENTS.md").write_text(
            "Hardlink rules.\n",
            encoding="utf-8",
        )
        capabilities = self._capabilities()
        scope_digest = self._scope_digest(
            capabilities,
            ".",
            target_is_directory=True,
        )

        with self.assertRaisesRegex(
            RuntimeToolError,
            "workspace_effect_hardlink_unsupported",
        ):
            capabilities["core-capability:shell.run"].handler(
                {
                    "argv": [
                        "/bin/sh",
                        "-c",
                        "printf x > new-a; ln new-a new-b",
                    ],
                    "mutation_scopes": [
                        {
                            "path": ".",
                            "instruction_scope_digest": scope_digest,
                        }
                    ],
                },
                self.context,
                None,
            )
        self.assertFalse((self.workspace / "new-a").exists())
        self.assertFalse((self.workspace / "new-b").exists())

        existing_a = self.workspace / "existing-a"
        existing_b = self.workspace / "existing-b"
        existing_a.write_text("old", encoding="utf-8")
        os.link(existing_a, existing_b)
        original_inode = existing_a.stat().st_ino
        with self.assertRaisesRegex(
            RuntimeToolError,
            "workspace_effect_hardlink_unsupported",
        ):
            capabilities["core-capability:shell.run"].handler(
                {
                    "argv": ["/bin/sh", "-c", "printf new > existing-a"],
                    "mutation_scopes": [
                        {
                            "path": ".",
                            "instruction_scope_digest": scope_digest,
                        }
                    ],
                },
                self.context,
                None,
            )
        self.assertEqual(existing_a.read_text(encoding="utf-8"), "old")
        self.assertEqual(existing_b.read_text(encoding="utf-8"), "old")
        self.assertEqual(existing_a.stat().st_ino, original_inode)
        self.assertEqual(existing_b.stat().st_ino, original_inode)

    def test_process_status_is_mutating_and_batch_failure_is_not_retry_safe(self) -> None:
        agents = self.workspace / "AGENTS.md"
        agents.write_text("Initial.\n", encoding="utf-8")

        def race(stage, path):
            if stage == "write_committed" and path == "process-b.txt":
                agents.write_text("Raced.\n", encoding="utf-8")

        capabilities = self._capabilities(processes=True, race_hook=race)
        status_surface = capabilities["core-capability:process.status"]
        self.assertEqual(status_surface.definition.effect_class, "mutating")
        self.assertFalse(status_surface.definition.safe_to_retry)
        scope_digest = self._scope_digest(
            capabilities,
            ".",
            target_is_directory=True,
        )
        started = capabilities["core-capability:process.start"].handler(
            {
                "argv": [
                    "/bin/sh",
                    "-c",
                    (
                        "printf first > process-a.txt; "
                        "printf second > process-b.txt"
                    ),
                ],
                "mutation_scopes": [
                    {
                        "path": ".",
                        "instruction_scope_digest": scope_digest,
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
                str(started.payload["process_id"]),
            )
        record = self.harness.store.get_process(str(started.payload["process_id"]))
        self.assertEqual(record.status, "failed")
        self.assertFalse((self.workspace / "process-a.txt").exists())
        self.assertFalse((self.workspace / "process-b.txt").exists())

    def test_mutation_requires_digest_and_rolls_back_instruction_races(self) -> None:
        agents = self.workspace / "AGENTS.md"
        agents.write_text("Initial.\n", encoding="utf-8")
        capabilities = self._capabilities()
        with self.assertRaisesRegex(RuntimeToolError, "tool_arguments_invalid"):
            capabilities["core-capability:filesystem.write"].handler(
                {
                    "path": "without-digest.txt",
                    "content": "not written",
                    "create_only": True,
                },
                self.context,
                None,
            )
        self.assertFalse((self.workspace / "without-digest.txt").exists())

        for race_stage in ("write_temporary_ready", "write_committed"):
            with self.subTest(race_stage=race_stage):
                agents.write_text("Initial.\n", encoding="utf-8")

                def race(stage, _path):
                    if stage == race_stage:
                        agents.write_text("Raced.\n", encoding="utf-8")

                racing = self._capabilities(race_hook=race)
                scope_digest = self._scope_digest(racing, "raced.txt")
                with self.assertRaisesRegex(
                    RuntimeToolError,
                    "workspace_instruction_scope_changed",
                ):
                    racing["core-capability:filesystem.write"].handler(
                        {
                            "path": "raced.txt",
                            "content": "must roll back",
                            "create_only": True,
                            "instruction_scope_digest": scope_digest,
                        },
                        self.context,
                        None,
                    )
                self.assertFalse((self.workspace / "raced.txt").exists())
                self.assertEqual(agents.read_text(encoding="utf-8"), "Raced.\n")

        for operation, race_stage in (("move", "move_committed"), ("delete", "delete_committed")):
            with self.subTest(operation=operation):
                agents.write_text("Initial.\n", encoding="utf-8")
                source = self.workspace / f"{operation}-source.txt"
                source.write_text("preserve me", encoding="utf-8")

                def race(stage, _path):
                    if stage == race_stage:
                        agents.write_text("Raced.\n", encoding="utf-8")

                racing = self._capabilities(race_hook=race)
                observed = racing["core-capability:filesystem.read"].handler(
                    {"path": source.name},
                    self.context,
                    None,
                )
                scope_digest = self._scope_digest(racing, source.name)
                arguments = {
                    "expected_resource_identity": observed.payload[
                        "resource_identity"
                    ],
                    "expected_resource_revision": observed.payload[
                        "resource_revision"
                    ],
                }
                if operation == "move":
                    destination = self.workspace / "moved.txt"
                    arguments.update(
                        source_path=source.name,
                        destination_path=destination.name,
                        source_instruction_scope_digest=scope_digest,
                        destination_instruction_scope_digest=scope_digest,
                    )
                else:
                    destination = None
                    arguments.update(
                        path=source.name,
                        instruction_scope_digest=scope_digest,
                    )
                with self.assertRaisesRegex(
                    RuntimeToolError,
                    "workspace_instruction_scope_changed",
                ):
                    racing[f"core-capability:filesystem.{operation}"].handler(
                        arguments,
                        self.context,
                        None,
                    )
                self.assertTrue(source.exists())
                if destination is not None:
                    self.assertFalse(destination.exists())

    def test_intentional_agents_move_is_bound_to_both_original_scopes(self) -> None:
        agents = self.workspace / "AGENTS.md"
        destination_directory = self.workspace / "nested"
        destination_directory.mkdir()
        agents.write_text("Relocate this instruction.\n", encoding="utf-8")
        capabilities = self._capabilities()
        observed = capabilities["core-capability:filesystem.read"].handler(
            {"path": "AGENTS.md"},
            self.context,
            None,
        )
        source_digest = self._scope_digest(capabilities, "AGENTS.md")
        destination_digest = self._scope_digest(
            capabilities,
            "nested/AGENTS.md",
        )

        capabilities["core-capability:filesystem.move"].handler(
            {
                "source_path": "AGENTS.md",
                "destination_path": "nested/AGENTS.md",
                "expected_resource_identity": observed.payload[
                    "resource_identity"
                ],
                "expected_resource_revision": observed.payload[
                    "resource_revision"
                ],
                "source_instruction_scope_digest": source_digest,
                "destination_instruction_scope_digest": destination_digest,
            },
            self.context,
            None,
        )

        self.assertFalse(agents.exists())
        self.assertEqual(
            (destination_directory / "AGENTS.md").read_text(encoding="utf-8"),
            "Relocate this instruction.\n",
        )


if __name__ == "__main__":
    unittest.main()
