from __future__ import annotations

from pathlib import Path
import tempfile
import time
import unittest

from core.runtime.process_control import runtime_processes_alive_for_session
from core.runtime.tool_errors import RuntimeToolError
from tests.support.cases.full_workspace_contract import FullWorkspaceContractFixture


class FullWorkspaceShellContractTest(FullWorkspaceContractFixture, unittest.TestCase):
    def test_search_cursor_and_versioned_mutations_fail_on_race(self) -> None:
        target = self.workspace / "race.txt"
        target.write_text("needle one\nneedle two\n", encoding="utf-8")
        capabilities = self._capabilities()
        first = capabilities["core-capability:filesystem.search"].handler(
            {"query": "needle", "max_results": 1},
            self.context,
            None,
        )
        target.write_text("changed\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeToolError, "filesystem_snapshot_changed"):
            capabilities["core-capability:filesystem.search"].handler(
                {"query": "ignored", "cursor": first.payload["next_cursor"]},
                self.context,
                None,
            )

        observed = capabilities["core-capability:filesystem.read"].handler(
            {"path": "race.txt"},
            self.context,
            None,
        )
        target.write_text("changed again\n", encoding="utf-8")
        scope_digest = self._scope_digest(capabilities, "race.txt")
        with self.assertRaisesRegex(RuntimeToolError, "filesystem_resource_changed"):
            capabilities["core-capability:filesystem.write"].handler(
                {
                    "path": "race.txt",
                    "content": "stale replacement",
                    "replace_only": True,
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
        self.assertEqual(target.read_text(encoding="utf-8"), "changed again\n")

    def test_recursive_delete_unlinks_symlink_without_touching_target(self) -> None:
        with tempfile.TemporaryDirectory() as outside_directory:
            outside = Path(outside_directory)
            protected = outside / "protected.txt"
            protected.write_text("outside", encoding="utf-8")
            tree = self.workspace / "tree"
            tree.mkdir()
            (tree / "local.txt").write_text("inside", encoding="utf-8")
            (tree / "link.txt").symlink_to(protected)
            capabilities = self._capabilities()
            scope_digest = self._scope_digest(
                capabilities,
                "tree",
                target_is_directory=True,
            )
            listing = capabilities["core-capability:filesystem.list"].handler(
                {"path": "."},
                self.context,
                None,
            )
            tree_entry = next(
                item
                for item in listing.payload["entries"]
                if item["path"] == "tree"
            )
            deleted = capabilities["core-capability:filesystem.delete"].handler(
                {
                    "path": "tree",
                    "recursive": True,
                    "expected_resource_identity": tree_entry["resource_identity"],
                    "expected_resource_revision": tree_entry["resource_revision"],
                    "instruction_scope_digest": scope_digest,
                },
                self.context,
                None,
            )
            self.assertEqual(deleted.payload["deleted_entry_count"], 3)
            self.assertTrue(protected.exists())
            self.assertEqual(protected.read_text(encoding="utf-8"), "outside")

    def test_shell_and_long_process_are_confined_streamed_and_reaped(self) -> None:
        capabilities = self._capabilities(processes=True)
        runtime_marker = self.workspace / "runtime" / "private-marker"
        runtime_marker.parent.mkdir(parents=True, exist_ok=True)
        runtime_marker.write_text("platform-private", encoding="utf-8")
        git_marker = self.workspace / ".git" / "private-marker"
        git_marker.parent.mkdir(parents=True, exist_ok=True)
        git_marker.write_text("repository-private", encoding="utf-8")
        nested_git_marker = self.workspace / "project" / ".git" / "private-marker"
        nested_git_marker.parent.mkdir(parents=True, exist_ok=True)
        nested_git_marker.write_text("nested-repository-private", encoding="utf-8")
        worktree_pointer = self.workspace / "worktree" / ".git"
        worktree_pointer.parent.mkdir(parents=True, exist_ok=True)
        worktree_pointer.write_text(
            "gitdir: /platform/private/nested-worktree\n",
            encoding="utf-8",
        )
        shell = capabilities["core-capability:shell.run"].handler(
            {
                "argv": [
                    "/bin/sh",
                    "-c",
                    (
                        "printf '%s|' \"$PWD\"; "
                        "test ! -e /etc/passwd && "
                        "test ! -e /workspace/runtime/private-marker && "
                        "test ! -e /workspace/.git/private-marker && "
                        "test ! -e /workspace/project/.git/private-marker && "
                        "test ! -s /workspace/worktree/.git && "
                        f"test ! -e {self.workspace!s} && printf confined"
                    ),
                ],
                "mutation_scopes": [],
            },
            self.context,
            None,
        )
        self.assertEqual(shell["output"], "/workspace|confined")

        fd_bypass = capabilities["core-capability:shell.run"].handler(
            {
                "argv": [
                    "/usr/bin/python3",
                    "-c",
                    (
                        "import os\n"
                        "for fd in range(3,128):\n"
                        " try:\n"
                        "  handle=os.open('descriptor-bypass.txt',"
                        "os.O_WRONLY|os.O_CREAT,0o600,dir_fd=fd)\n"
                        "  os.write(handle,b'bypass'); os.close(handle)\n"
                        " except OSError: pass\n"
                    ),
                ],
                "mutation_scopes": [],
            },
            self.context,
            None,
        )
        self.assertEqual(fd_bypass["exit_code"], 0)
        self.assertFalse((self.workspace / "descriptor-bypass.txt").exists())

        started = capabilities["core-capability:process.start"].handler(
            {
                "argv": [
                    "/bin/sh",
                    "-c",
                    (
                        "test ! -e /workspace/runtime/private-marker && "
                        "test ! -e /workspace/.git/private-marker && "
                        "test ! -e /workspace/project/.git/private-marker && "
                        "test ! -s /workspace/worktree/.git && "
                        "read value; printf 'received:%s' \"$value\""
                    ),
                ],
                "mutation_scopes": [],
            },
            self.context,
            None,
        )
        process_id = started.payload["process_id"]
        capabilities["core-capability:process.input"].handler(
            {"process_id": process_id, "content": "hello\n", "close": True},
            self.context,
            None,
        )
        status = None
        for _ in range(50):
            status = capabilities["core-capability:process.status"].handler(
                {"process_id": process_id},
                self.context,
                None,
            )
            if status.payload["status"] == "exited":
                break
            time.sleep(0.02)
        assert status is not None
        self.assertEqual(status.payload["status"], "exited")
        self.assertEqual(status.payload["output"], "received:hello")
        self.assertFalse(runtime_processes_alive_for_session("session-hosted"))

    def test_shell_and_process_overlays_mask_nested_git_metadata(self) -> None:
        (self.workspace / "AGENTS.md").write_text(
            "Nested Git metadata must stay private.\n",
            encoding="utf-8",
        )
        nested_marker = self.workspace / "project" / ".git" / "private-marker"
        nested_marker.parent.mkdir(parents=True)
        nested_marker.write_text("nested-private", encoding="utf-8")
        pointer = self.workspace / "worktree" / ".git"
        pointer.parent.mkdir(parents=True)
        pointer.write_text(
            "gitdir: /platform/private/worktree\n",
            encoding="utf-8",
        )
        capabilities = self._capabilities(processes=True)
        scope_digest = self._scope_digest(
            capabilities,
            ".",
            target_is_directory=True,
        )
        mutation_scopes = [
            {
                "path": ".",
                "instruction_scope_digest": scope_digest,
            }
        ]
        probe = (
            "test ! -e /workspace/project/.git/private-marker && "
            "test ! -s /workspace/worktree/.git"
        )

        shell = capabilities["core-capability:shell.run"].handler(
            {
                "argv": [
                    "/bin/sh",
                    "-c",
                    f"{probe} && printf shell > shell-overlay.txt",
                ],
                "mutation_scopes": mutation_scopes,
            },
            self.context,
            None,
        )
        self.assertEqual(shell["exit_code"], 0)
        self.assertEqual(
            (self.workspace / "shell-overlay.txt").read_text(encoding="utf-8"),
            "shell",
        )

        started = capabilities["core-capability:process.start"].handler(
            {
                "argv": [
                    "/bin/sh",
                    "-c",
                    f"{probe} && printf process > process-overlay.txt",
                ],
                "mutation_scopes": mutation_scopes,
            },
            self.context,
            None,
        )
        status = self._wait_for_process(
            capabilities,
            str(started.payload["process_id"]),
        )
        self.assertEqual(status.payload["status"], "exited")
        self.assertEqual(status.payload["exit_code"], 0)
        self.assertEqual(
            (self.workspace / "process-overlay.txt").read_text(encoding="utf-8"),
            "process",
        )


if __name__ == "__main__":
    unittest.main()
