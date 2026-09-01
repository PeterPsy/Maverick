from __future__ import annotations

import base64
from datetime import UTC, datetime
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from core.runtime.confined_filesystem import ConfinedWorkspaceFilesystem
from core.runtime.tool_errors import RuntimeToolError
from core.runtime.confined_filesystem_mutation_support import (
    rename_exchange as real_rename_exchange,
    rename_noreplace as real_rename_noreplace,
)


NOW = datetime(2026, 8, 26, tzinfo=UTC)


class ConfinedWorkspaceFilesystemTest(unittest.TestCase):
    def test_binary_chunks_are_readable_as_version_fenced_base64(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            raw = b"%PDF-1.7\x00\xfffixture"
            (root / "evidence.pdf").write_bytes(raw)
            filesystem = ConfinedWorkspaceFilesystem(
                workspace_id="default",
                workspace_root=root,
            )

            first = filesystem.read_bytes("evidence.pdf", max_bytes=7)
            second = filesystem.read_bytes(
                "evidence.pdf",
                offset=int(first.payload["next_offset"]),
                max_bytes=64,
                expected_resource_identity=str(first.payload["resource_identity"]),
                expected_resource_revision=str(first.payload["resource_revision"]),
            )

            decoded = base64.b64decode(str(first.payload["content_base64"]))
            decoded += base64.b64decode(str(second.payload["content_base64"]))
            self.assertEqual(decoded, raw)
            self.assertEqual(first.payload["encoding"], "base64")
            self.assertTrue(first.payload["truncated"])
            self.assertFalse(second.payload["truncated"])

    def test_atomic_replace_preserves_every_inode_across_final_entry_swap(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            target = root / "target.txt"
            attacker = root / "attacker.txt"
            displaced = root / "displaced.txt"
            target.write_text("original", encoding="utf-8")
            attacker.write_text("attacker", encoding="utf-8")
            filesystem = ConfinedWorkspaceFilesystem(
                workspace_id="default",
                workspace_root=root,
            )
            observed = filesystem.read_text("target.txt", max_bytes=64)
            raced = False

            def exchange_with_swap(*args):
                nonlocal raced
                if not raced:
                    raced = True
                    target.rename(displaced)
                    attacker.rename(target)
                return real_rename_exchange(*args)

            with patch(
                "core.runtime.confined_filesystem.rename_exchange",
                side_effect=exchange_with_swap,
            ), self.assertRaisesRegex(RuntimeToolError, "tool_execution_unknown"):
                filesystem.write_text(
                    "target.txt",
                    content="intended",
                    create_only=False,
                    replace_only=True,
                    expected_resource_identity=str(
                        observed.payload["resource_identity"]
                    ),
                    expected_resource_revision=str(
                        observed.payload["resource_revision"]
                    ),
                )

            contents = sorted(
                path.read_text(encoding="utf-8")
                for path in root.iterdir()
                if path.is_file()
            )
            self.assertEqual(contents, ["attacker", "intended", "original"])

    def test_replace_preserves_mode_and_extended_attributes(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            target = root / "script.sh"
            target.write_text("#!/bin/sh\necho old\n", encoding="utf-8")
            target.chmod(0o755)
            try:
                os.setxattr(target, "user.maverick.fixture", b"retained")
            except OSError as error:
                self.skipTest(f"filesystem xattrs unavailable: {error}")
            filesystem = ConfinedWorkspaceFilesystem(
                workspace_id="default",
                workspace_root=root,
            )
            observed = filesystem.read_text("script.sh", max_bytes=128)

            filesystem.write_text(
                "script.sh",
                content="#!/bin/sh\necho new\n",
                create_only=False,
                replace_only=True,
                expected_resource_identity=str(
                    observed.payload["resource_identity"]
                ),
                expected_resource_revision=str(
                    observed.payload["resource_revision"]
                ),
            )

            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o755)
            self.assertEqual(
                os.getxattr(target, "user.maverick.fixture"),
                b"retained",
            )

    def test_failed_mutations_remove_every_created_parent(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            filesystem = ConfinedWorkspaceFilesystem(
                workspace_id="default",
                workspace_root=root,
            )

            with self.assertRaisesRegex(
                RuntimeToolError,
                "filesystem_resource_changed",
            ):
                filesystem.write_text(
                    "new/deep/file.txt",
                    content="blocked",
                    create_only=False,
                    create_parents=True,
                    expected_resource_identity="missing-identity",
                    expected_resource_revision="missing-revision",
                )
            self.assertFalse((root / "new").exists())

            with self.assertRaisesRegex(
                RuntimeToolError,
                "filesystem_path_not_found",
            ):
                filesystem.move_path(
                    "missing.txt",
                    "destination/deep/moved.txt",
                    expected_resource_identity="missing-identity",
                    expected_resource_revision="missing-revision",
                    create_parents=True,
                )
            self.assertFalse((root / "destination").exists())

    def test_move_and_delete_rollback_an_inode_swapped_at_atomic_commit(self) -> None:
        for operation in ("move", "delete"):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as root_dir:
                root = Path(root_dir)
                target = root / "target.txt"
                attacker = root / "attacker.txt"
                displaced = root / "displaced.txt"
                target.write_text("original", encoding="utf-8")
                attacker.write_text("attacker", encoding="utf-8")
                filesystem = ConfinedWorkspaceFilesystem(
                    workspace_id="default",
                    workspace_root=root,
                )
                observed = filesystem.read_text("target.txt", max_bytes=64)
                raced = False

                def rename_with_swap(*args):
                    nonlocal raced
                    if not raced:
                        raced = True
                        target.rename(displaced)
                        attacker.rename(target)
                    return real_rename_noreplace(*args)

                module = (
                    "core.runtime.confined_filesystem_mutations.rename_noreplace"
                    if operation == "move"
                    else "core.runtime.confined_filesystem_delete.rename_noreplace"
                )
                with patch(module, side_effect=rename_with_swap), self.assertRaisesRegex(
                    RuntimeToolError,
                    "filesystem_resource_changed",
                ):
                    if operation == "move":
                        filesystem.move_path(
                            "target.txt",
                            "moved.txt",
                            expected_resource_identity=str(
                                observed.payload["resource_identity"]
                            ),
                            expected_resource_revision=str(
                                observed.payload["resource_revision"]
                            ),
                        )
                    else:
                        filesystem.delete_path(
                            "target.txt",
                            expected_resource_identity=str(
                                observed.payload["resource_identity"]
                            ),
                            expected_resource_revision=str(
                                observed.payload["resource_revision"]
                            ),
                        )
                self.assertEqual(target.read_text(encoding="utf-8"), "attacker")
                self.assertEqual(displaced.read_text(encoding="utf-8"), "original")
                self.assertFalse((root / "moved.txt").exists())

    def test_pinned_root_rejects_rename_swap_for_read_list_and_write(self) -> None:
        for operation in ("read", "list", "write"):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as parent_dir, tempfile.TemporaryDirectory() as outside_dir:
                parent = Path(parent_dir)
                root = parent / "workspace"
                root.mkdir()
                (root / "inside.txt").write_text("inside", encoding="utf-8")
                outside = Path(outside_dir)
                (outside / "outside.txt").write_text("outside", encoding="utf-8")
                filesystem = ConfinedWorkspaceFilesystem(
                    workspace_id="default",
                    workspace_root=root,
                )
                moved = parent / "moved-workspace"
                root.rename(moved)
                root.symlink_to(outside, target_is_directory=True)

                with self.assertRaisesRegex(RuntimeToolError, "filesystem_root_moved"):
                    if operation == "read":
                        filesystem.read_text("inside.txt", max_bytes=64)
                    elif operation == "list":
                        filesystem.list_entries(".", max_depth=1, page_size=10)
                    else:
                        filesystem.write_text(
                            "escaped.txt",
                            content="must-not-escape",
                            create_only=True,
                        )
                self.assertFalse((outside / "escaped.txt").exists())
                filesystem.close()

    def test_read_rejects_final_and_parent_symlink_swaps_repeatedly(self) -> None:
        for iteration in range(25):
            with self.subTest(iteration=iteration), tempfile.TemporaryDirectory() as root_dir, tempfile.TemporaryDirectory() as outside_dir:
                root = Path(root_dir)
                outside = Path(outside_dir)
                (root / "target.txt").write_text("inside", encoding="utf-8")
                (outside / "secret.txt").write_text("outside-secret", encoding="utf-8")

                def final_swap(event: str, _path: str) -> None:
                    if event == "read_parent_opened":
                        (root / "target.txt").unlink()
                        (root / "target.txt").symlink_to(outside / "secret.txt")

                filesystem = ConfinedWorkspaceFilesystem(
                    workspace_id="default",
                    workspace_root=root,
                    race_hook=final_swap,
                )
                with self.assertRaises(RuntimeToolError) as raised:
                    filesystem.read_text("target.txt", max_bytes=64)
                self.assertNotIn("outside-secret", str(raised.exception))

                (root / "target.txt").unlink()
                parent = root / "parent"
                parent.mkdir()
                (parent / "target.txt").write_text("inside-parent", encoding="utf-8")
                moved = outside / "moved-parent"

                def parent_swap(event: str, _path: str) -> None:
                    if event == "read_file_opened":
                        parent.rename(moved)
                        parent.symlink_to(outside, target_is_directory=True)

                filesystem = ConfinedWorkspaceFilesystem(
                    workspace_id="default",
                    workspace_root=root,
                    race_hook=parent_swap,
                )
                with self.assertRaisesRegex(RuntimeToolError, "filesystem_resource_changed"):
                    filesystem.read_text("parent/target.txt", max_bytes=64)

    def test_directory_rename_before_and_after_commit_never_leaves_write_outside(self) -> None:
        for event in ("write_temporary_ready", "write_committed"):
            for iteration in range(20):
                with self.subTest(event=event, iteration=iteration), tempfile.TemporaryDirectory() as root_dir, tempfile.TemporaryDirectory() as outside_dir:
                    root = Path(root_dir)
                    outside = Path(outside_dir)
                    parent = root / "parent"
                    parent.mkdir()
                    moved = outside / f"moved-{iteration}"

                    def rename_parent(actual_event: str, _path: str) -> None:
                        if actual_event == event:
                            parent.rename(moved)
                            parent.symlink_to(outside, target_is_directory=True)

                    filesystem = ConfinedWorkspaceFilesystem(
                        workspace_id="default",
                        workspace_root=root,
                        race_hook=rename_parent,
                    )
                    with self.assertRaises(RuntimeToolError):
                        filesystem.write_text(
                            "parent/escaped.txt",
                            content="must-not-escape",
                            create_only=True,
                        )

                    self.assertFalse((outside / "escaped.txt").exists())
                    self.assertFalse((moved / "escaped.txt").exists())
                    self.assertFalse(
                        any(path.name.startswith(".maverick-write-") for path in moved.iterdir())
                    )


if __name__ == "__main__":
    unittest.main()
