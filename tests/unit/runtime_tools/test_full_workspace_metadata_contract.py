from __future__ import annotations

import os
from pathlib import Path
import stat
import time
import unittest

from core.runtime.tool_errors import RuntimeToolError
from tests.support.cases.full_workspace_contract import FullWorkspaceContractFixture


class FullWorkspaceMetadataContractTest(FullWorkspaceContractFixture, unittest.TestCase):
    def test_shell_overlay_rolls_back_every_file_after_late_batch_race(self) -> None:
        agents = self.workspace / "AGENTS.md"
        agents.write_text("Initial.\n", encoding="utf-8")
        existing = self.workspace / "0-existing.txt"
        existing.write_text("original", encoding="utf-8")

        def race(stage, path):
            if stage == "write_committed" and path == "b.txt":
                agents.write_text("Raced.\n", encoding="utf-8")

        capabilities = self._capabilities(race_hook=race)
        scope_digest = self._scope_digest(
            capabilities,
            ".",
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
                        (
                            "printf replacement > 0-existing.txt; "
                            "printf first > a.txt; printf second > b.txt"
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
        self.assertFalse((self.workspace / "a.txt").exists())
        self.assertFalse((self.workspace / "b.txt").exists())
        self.assertEqual(existing.read_text(encoding="utf-8"), "original")
        self.assertEqual(agents.read_text(encoding="utf-8"), "Raced.\n")

    def test_shell_overlay_rolls_back_concurrent_later_file_metadata(self) -> None:
        (self.workspace / "AGENTS.md").write_text(
            "Metadata race rules.\n",
            encoding="utf-8",
        )
        first = self.workspace / "a.txt"
        second = self.workspace / "b.txt"
        first.write_text("first-old", encoding="utf-8")
        second.write_text("second-old", encoding="utf-8")
        try:
            os.setxattr(second, "user.maverick.race-probe", b"probe")
            os.removexattr(second, "user.maverick.race-probe")
        except OSError as error:
            self.skipTest(f"filesystem xattrs unavailable: {error}")

        def race(stage, path):
            if stage == "write_committed" and path == "a.txt":
                os.setxattr(second, "user.maverick.concurrent", b"retained")

        capabilities = self._capabilities(race_hook=race)
        scope_digest = self._scope_digest(
            capabilities,
            ".",
            target_is_directory=True,
        )
        with self.assertRaisesRegex(
            RuntimeToolError,
            "filesystem_resource_changed",
        ):
            capabilities["core-capability:shell.run"].handler(
                {
                    "argv": [
                        "/bin/sh",
                        "-c",
                        "printf first-new > a.txt; printf second-new > b.txt",
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

        self.assertEqual(first.read_text(encoding="utf-8"), "first-old")
        self.assertEqual(second.read_text(encoding="utf-8"), "second-old")
        self.assertEqual(
            os.getxattr(second, "user.maverick.concurrent"),
            b"retained",
        )

    def test_shell_and_process_preserve_existing_file_metadata(self) -> None:
        agents = self.workspace / "AGENTS.md"
        agents.write_text("Metadata rules.\n", encoding="utf-8")
        shell_target = self.workspace / "shell-script.sh"
        process_target = self.workspace / "process-script.sh"
        expected_atimes: dict[Path, int] = {}
        for target in (shell_target, process_target):
            target.write_text("old\n", encoding="utf-8")
            target.chmod(0o755)
            try:
                os.setxattr(target, "user.maverick.fixture", b"retained")
            except OSError as error:
                self.skipTest(f"filesystem xattrs unavailable: {error}")
            old_atime_ns = time.time_ns() - 86_400_000_000_000
            os.utime(
                target,
                ns=(old_atime_ns, target.stat().st_mtime_ns),
            )
            expected_atimes[target] = old_atime_ns
        expected_owner = (shell_target.stat().st_uid, shell_target.stat().st_gid)
        capabilities = self._capabilities(processes=True)
        scope_digest = self._scope_digest(
            capabilities,
            ".",
            target_is_directory=True,
        )

        shell = capabilities["core-capability:shell.run"].handler(
            {
                "argv": ["/bin/sh", "-c", "printf shell-new > shell-script.sh"],
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
        self.assertTrue(shell["workspace_effects_committed"])

        started = capabilities["core-capability:process.start"].handler(
            {
                "argv": [
                    "/bin/sh",
                    "-c",
                    "printf process-new > process-script.sh",
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
        terminal = self._wait_for_process(
            capabilities,
            str(started.payload["process_id"]),
        )
        self.assertEqual(terminal.payload["status"], "exited")

        for target, expected_content in (
            (shell_target, "shell-new"),
            (process_target, "process-new"),
        ):
            with self.subTest(path=target.name):
                current = target.stat()
                self.assertEqual(target.read_text(encoding="utf-8"), expected_content)
                self.assertEqual(stat.S_IMODE(current.st_mode), 0o755)
                self.assertEqual((current.st_uid, current.st_gid), expected_owner)
                self.assertEqual(current.st_atime_ns, expected_atimes[target])
                self.assertEqual(
                    os.getxattr(target, "user.maverick.fixture"),
                    b"retained",
                )

    def test_edit_and_patch_preserve_existing_file_metadata(self) -> None:
        (self.workspace / "AGENTS.md").write_text(
            "Direct edit metadata rules.\n",
            encoding="utf-8",
        )
        target = self.workspace / "editable-script.sh"
        target.write_text("#!/bin/sh\necho old\n", encoding="utf-8")
        target.chmod(0o755)
        try:
            os.setxattr(target, "user.maverick.fixture", b"retained")
        except OSError as error:
            self.skipTest(f"filesystem xattrs unavailable: {error}")
        capabilities = self._capabilities()
        scope_digest = self._scope_digest(capabilities, "editable-script.sh")
        observed = capabilities["core-capability:filesystem.read"].handler(
            {"path": "editable-script.sh"},
            self.context,
            None,
        )

        edited = capabilities["core-capability:filesystem.edit"].handler(
            {
                "path": "editable-script.sh",
                "old_text": "old",
                "new_text": "edited",
                "expected_resource_identity": observed.payload[
                    "resource_identity"
                ],
                "expected_resource_revision": observed.payload[
                    "resource_revision"
                ],
                "instruction_scope_digest": scope_digest,
            },
            self.context,
            None,
        )
        patched = capabilities["core-capability:filesystem.patch"].handler(
            {
                "path": "editable-script.sh",
                "operations": [
                    {"old_text": "edited", "new_text": "patched"},
                ],
                "expected_resource_identity": edited.payload[
                    "resource_identity"
                ],
                "expected_resource_revision": edited.payload[
                    "resource_revision"
                ],
                "instruction_scope_digest": scope_digest,
            },
            self.context,
            None,
        )

        self.assertEqual(patched.payload["path"], "editable-script.sh")
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o755)
        self.assertEqual(
            os.getxattr(target, "user.maverick.fixture"),
            b"retained",
        )

    def test_shell_overlay_supports_read_modify_write_and_read_after_write(self) -> None:
        (self.workspace / "AGENTS.md").write_text(
            "Read-modify-write rules.\n",
            encoding="utf-8",
        )
        sed_target = self.workspace / "sed-existing.txt"
        read_target = self.workspace / "read-after-write.txt"
        sed_target.write_text("old value\n", encoding="utf-8")
        read_target.write_text("old\n", encoding="utf-8")
        old_atime_ns = time.time_ns() - 86_400_000_000_000
        os.utime(
            read_target,
            ns=(old_atime_ns, read_target.stat().st_mtime_ns),
        )
        capabilities = self._capabilities()
        scope_digest = self._scope_digest(
            capabilities,
            ".",
            target_is_directory=True,
        )

        sed_result = capabilities["core-capability:shell.run"].handler(
            {
                "argv": [
                    "/bin/sed",
                    "-i",
                    "s/old/new/",
                    "sed-existing.txt",
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
        self.assertTrue(sed_result["workspace_effects_committed"])
        self.assertEqual(sed_target.read_text(encoding="utf-8"), "new value\n")

        read_result = capabilities["core-capability:shell.run"].handler(
            {
                "argv": [
                    "/bin/sh",
                    "-c",
                    (
                        "printf new > read-after-write.txt; "
                        "cat read-after-write.txt >/dev/null"
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
        self.assertTrue(read_result["workspace_effects_committed"])
        committed = read_target.stat()
        self.assertGreater(committed.st_atime_ns, old_atime_ns)
        self.assertEqual(read_target.read_text(encoding="utf-8"), "new")


if __name__ == "__main__":
    unittest.main()
