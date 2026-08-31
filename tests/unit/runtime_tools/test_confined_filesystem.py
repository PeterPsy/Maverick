"""Linux race and mutation gates for the fd-relative workspace filesystem."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from core.runtime.confined_filesystem import (
    ConfinedWorkspaceFilesystem,
    FilesystemResourceObservation,
)
from core.runtime.tool_errors import RuntimeToolError
from core.runtime.confined_filesystem_mutation_support import (
    rename_exchange as real_rename_exchange,
    rename_noreplace as real_rename_noreplace,
)
from core.workspaces.data_governance import (
    WorkspaceResourceClassification,
    resource_classification_for_observation,
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

    def test_list_detects_parent_rename_and_never_descends_into_git(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir, tempfile.TemporaryDirectory() as outside_dir:
            root = Path(root_dir)
            outside = Path(outside_dir)
            child = root / "child"
            child.mkdir()
            (child / "inside.txt").write_text("inside", encoding="utf-8")
            (root / ".git").mkdir()
            (root / ".git" / "never-listed").write_text("secret", encoding="utf-8")
            moved = outside / "moved-child"

            clean = ConfinedWorkspaceFilesystem(workspace_id="default", workspace_root=root)
            result = clean.list_entries(".", max_depth=3, page_size=100)
            self.assertNotIn(".git", str(result.payload["entries"]))

            def rename_after_scan(event: str, _path: str) -> None:
                if event == "list_scanned":
                    child.rename(moved)
                    child.symlink_to(outside, target_is_directory=True)

            racing = ConfinedWorkspaceFilesystem(
                workspace_id="default",
                workspace_root=root,
                race_hook=rename_after_scan,
            )
            with self.assertRaises(RuntimeToolError):
                racing.list_entries(".", max_depth=3, page_size=100)

    def test_listing_is_breadth_first_and_detects_file_content_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            child = root / "a-directory"
            child.mkdir()
            nested = child / "nested.txt"
            nested.write_text("initial", encoding="utf-8")
            (root / "z-top-level.txt").write_text("top", encoding="utf-8")
            clean = ConfinedWorkspaceFilesystem(
                workspace_id="default",
                workspace_root=root,
            )

            listed = clean.list_entries(".", max_depth=3, page_size=100)
            depths = [int(item["depth"]) for item in listed.payload["entries"]]
            self.assertEqual(depths, sorted(depths))

            def mutate_file_after_scan(event: str, _path: str) -> None:
                if event == "list_scanned":
                    nested.write_text("changed", encoding="utf-8")

            racing = ConfinedWorkspaceFilesystem(
                workspace_id="default",
                workspace_root=root,
                race_hook=mutate_file_after_scan,
            )
            with self.assertRaisesRegex(
                RuntimeToolError,
                "filesystem_snapshot_changed",
            ):
                racing.list_entries(".", max_depth=3, page_size=100)

    def test_write_reports_post_commit_version_and_detects_content_swap(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            filesystem = ConfinedWorkspaceFilesystem(
                workspace_id="default",
                workspace_root=root,
            )
            written = filesystem.write_text(
                "written.txt",
                content="stable",
                create_only=True,
            )
            read = filesystem.read_text(
                "written.txt",
                max_bytes=64,
                expected_resource_identity=str(written.payload["resource_identity"]),
                expected_resource_revision=str(written.payload["resource_revision"]),
            )
            self.assertEqual(read.payload["content"], "stable")

            def modify_committed_file(event: str, _path: str) -> None:
                if event == "write_committed":
                    (root / "raced.txt").write_text("attacker", encoding="utf-8")

            racing = ConfinedWorkspaceFilesystem(
                workspace_id="default",
                workspace_root=root,
                race_hook=modify_committed_file,
            )
            with self.assertRaisesRegex(
                RuntimeToolError,
                "filesystem_resource_changed",
            ):
                racing.write_text(
                    "raced.txt",
                    content="intended",
                    create_only=True,
                )
            self.assertFalse((root / "raced.txt").exists())

    def test_in_call_and_cross_chunk_mutations_are_detected_with_utf8_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            path = root / "utf8.txt"
            path.write_text("a€b", encoding="utf-8")
            filesystem = ConfinedWorkspaceFilesystem(
                workspace_id="default",
                workspace_root=root,
            )

            first = filesystem.read_text("utf8.txt", max_bytes=2)
            self.assertEqual(first.payload["content"], "a")
            second = filesystem.read_text(
                "utf8.txt",
                offset=int(first.payload["next_offset"]),
                max_bytes=4,
                expected_resource_identity=str(first.payload["resource_identity"]),
                expected_resource_revision=str(first.payload["resource_revision"]),
            )
            self.assertEqual(second.payload["content"], "€b")
            with self.assertRaises(RuntimeToolError):
                filesystem.read_text(
                    "utf8.txt",
                    offset=2,
                    max_bytes=2,
                    expected_resource_identity=str(first.payload["resource_identity"]),
                    expected_resource_revision=str(first.payload["resource_revision"]),
                )

            path.write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeToolError, "filesystem_resource_changed"):
                filesystem.read_text(
                    "utf8.txt",
                    offset=1,
                    max_bytes=2,
                    expected_resource_identity=str(first.payload["resource_identity"]),
                    expected_resource_revision=str(first.payload["resource_revision"]),
                )

            def mutate_open_file(event: str, _path: str) -> None:
                if event == "read_file_opened":
                    path.write_text("raced", encoding="utf-8")

            racing = ConfinedWorkspaceFilesystem(
                workspace_id="default",
                workspace_root=root,
                race_hook=mutate_open_file,
            )
            with self.assertRaisesRegex(RuntimeToolError, "filesystem_resource_changed"):
                racing.read_text("utf8.txt", max_bytes=64)

    def test_pagination_is_snapshot_bound_and_reports_resource_identity(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            for name in ("a.txt", "b.txt", "c.txt"):
                (root / name).write_text(name, encoding="utf-8")
            filesystem = ConfinedWorkspaceFilesystem(
                workspace_id="default",
                workspace_root=root,
                cursor_key=b"filesystem-cursor-test-key-32-bytes",
            )

            first = filesystem.list_entries(".", max_depth=1, page_size=1)
            self.assertEqual(first.payload["result_count"], 1)
            self.assertTrue(first.payload["next_cursor"])
            self.assertTrue(first.payload["resource_identity"])
            self.assertEqual(len(str(first.payload["resource_revision"])), 64)
            second = filesystem.list_entries(
                ".",
                max_depth=4,
                page_size=99,
                cursor=str(first.payload["next_cursor"]),
            )
            self.assertEqual(second.payload["snapshot_id"], first.payload["snapshot_id"])
            self.assertEqual(second.payload["result_count"], 1)

            (root / "d.txt").write_text("mutated", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeToolError, "filesystem_snapshot_changed"):
                filesystem.list_entries(
                    ".",
                    max_depth=1,
                    page_size=1,
                    cursor=str(second.payload["next_cursor"]),
                )
            with self.assertRaisesRegex(RuntimeToolError, "filesystem_cursor_invalid"):
                filesystem.list_entries(
                    ".",
                    max_depth=1,
                    page_size=1,
                    cursor=str(first.payload["next_cursor"]) + "forged",
                )

    def test_classification_is_derived_from_exact_observed_resource_version(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            path = root / "fixture.txt"
            path.write_text("synthetic", encoding="utf-8")
            unclassified = ConfinedWorkspaceFilesystem(
                workspace_id="default",
                workspace_root=root,
            ).read_text("fixture.txt", max_bytes=64)
            record = WorkspaceResourceClassification(
                classification_id="classification-1",
                workspace_id="default",
                resource_kind="filesystem_file",
                resource_ref="fixture.txt",
                resource_identity=str(unclassified.payload["resource_identity"]),
                resource_revision=str(unclassified.payload["resource_revision"]),
                resource_digest=str(unclassified.payload["resource_digest"]),
                data_class="public",
                trust_level="trusted_actor",
                revision=3,
                classified_by_actor_id="operator-1",
                classified_at=NOW,
                updated_at=NOW,
            )

            def resolve(observation: FilesystemResourceObservation, provenance: str):
                return resource_classification_for_observation(
                    record,
                    workspace_id=observation.workspace_id,
                    resource_kind=observation.resource_kind,
                    resource_ref=observation.resource_ref,
                    resource_identity=observation.resource_identity,
                    resource_revision=observation.resource_revision,
                    resource_digest=observation.resource_digest,
                    provenance=provenance,
                )

            classified_fs = ConfinedWorkspaceFilesystem(
                workspace_id="default",
                workspace_root=root,
                classification_resolver=resolve,
            )
            classified = classified_fs.read_text("fixture.txt", max_bytes=64)
            self.assertEqual(classified.classification.data_class, "public")
            self.assertEqual(classified.classification.classification_revision, 3)
            observation, attachment_classification = classified_fs.observe_file(
                "fixture.txt",
                provenance="attachment",
            )
            self.assertEqual(observation.resource_identity, record.resource_identity)
            self.assertEqual(attachment_classification.provenance, "attachment")
            self.assertEqual(attachment_classification.data_class, "public")

            path.write_text("real data now", encoding="utf-8")
            changed = classified_fs.read_text("fixture.txt", max_bytes=64)
            self.assertEqual(changed.classification.data_class, "unclassified")
            _, changed_attachment = classified_fs.observe_file(
                "fixture.txt",
                provenance="attachment",
            )
            self.assertEqual(changed_attachment.data_class, "unclassified")

    def test_mutation_taint_follows_public_preimage_through_read_after_write(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            path = root / "fixture.txt"
            path.write_text("public before", encoding="utf-8")
            initial = ConfinedWorkspaceFilesystem(
                workspace_id="default",
                workspace_root=root,
            ).read_text("fixture.txt", max_bytes=64)
            record = WorkspaceResourceClassification(
                classification_id="classification-postimage-1",
                workspace_id="default",
                resource_kind="filesystem_file",
                resource_ref="fixture.txt",
                resource_identity=str(initial.payload["resource_identity"]),
                resource_revision=str(initial.payload["resource_revision"]),
                resource_digest=str(initial.payload["resource_digest"]),
                data_class="public",
                trust_level="trusted_actor",
                revision=1,
                classified_by_actor_id="operator-1",
                classified_at=NOW,
                updated_at=NOW,
            )

            def resolve(observation: FilesystemResourceObservation, provenance: str):
                return resource_classification_for_observation(
                    record,
                    workspace_id=observation.workspace_id,
                    resource_kind=observation.resource_kind,
                    resource_ref=observation.resource_ref,
                    resource_identity=observation.resource_identity,
                    resource_revision=observation.resource_revision,
                    resource_digest=observation.resource_digest,
                    provenance=provenance,
                )

            filesystem = ConfinedWorkspaceFilesystem(
                workspace_id="default",
                workspace_root=root,
                classification_resolver=resolve,
            )
            before = filesystem.read_text("fixture.txt", max_bytes=64)
            written = filesystem.write_text(
                "fixture.txt",
                content="public after",
                create_only=False,
                replace_only=True,
                expected_resource_identity=str(
                    before.payload["resource_identity"]
                ),
                expected_resource_revision=str(
                    before.payload["resource_revision"]
                ),
            )
            reread = filesystem.read_text("fixture.txt", max_bytes=64)
            moved = filesystem.move_path(
                "fixture.txt",
                "moved.txt",
                expected_resource_identity=str(
                    reread.payload["resource_identity"]
                ),
                expected_resource_revision=str(
                    reread.payload["resource_revision"]
                ),
                create_parents=False,
            )
            moved_read = filesystem.read_text("moved.txt", max_bytes=64)

            self.assertEqual(written.classification.data_class, "public")
            self.assertEqual(reread.classification.data_class, "public")
            self.assertEqual(moved.classification.data_class, "public")
            self.assertEqual(moved_read.classification.data_class, "public")

            (root / "moved.txt").write_text("out-of-band", encoding="utf-8")
            changed = filesystem.read_text("moved.txt", max_bytes=64)
            self.assertEqual(changed.classification.data_class, "unclassified")

    def test_listing_classification_is_bound_to_the_exact_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            (root / "a.txt").write_text("a", encoding="utf-8")
            initial = ConfinedWorkspaceFilesystem(
                workspace_id="default",
                workspace_root=root,
            ).list_entries(".", max_depth=1, page_size=100)
            record = WorkspaceResourceClassification(
                classification_id="classification-listing-1",
                workspace_id="default",
                resource_kind="filesystem_listing",
                resource_ref=".",
                resource_identity=str(initial.payload["resource_identity"]),
                resource_revision=str(initial.payload["resource_revision"]),
                resource_digest=str(initial.payload["resource_digest"]),
                data_class="public",
                trust_level="trusted_actor",
                revision=1,
                classified_by_actor_id="operator-1",
                classified_at=NOW,
                updated_at=NOW,
            )

            def resolve(observation: FilesystemResourceObservation, provenance: str):
                return resource_classification_for_observation(
                    record,
                    workspace_id=observation.workspace_id,
                    resource_kind=observation.resource_kind,
                    resource_ref=observation.resource_ref,
                    resource_identity=observation.resource_identity,
                    resource_revision=observation.resource_revision,
                    resource_digest=observation.resource_digest,
                    provenance=provenance,
                )

            filesystem = ConfinedWorkspaceFilesystem(
                workspace_id="default",
                workspace_root=root,
                classification_resolver=resolve,
            )
            classified = filesystem.list_entries(
                ".",
                max_depth=1,
                page_size=100,
            )
            self.assertEqual(classified.classification.data_class, "public")

            (root / "b.txt").write_text("b", encoding="utf-8")
            changed = filesystem.list_entries(".", max_depth=1, page_size=100)
            self.assertEqual(changed.classification.data_class, "unclassified")

    def test_explicit_git_and_shell_cwd_swaps_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir, tempfile.TemporaryDirectory() as outside_dir:
            root = Path(root_dir)
            outside = Path(outside_dir)
            (root / ".git").mkdir()
            cwd = root / "cwd"
            cwd.mkdir()
            with self.assertRaises(RuntimeToolError):
                ConfinedWorkspaceFilesystem(
                    workspace_id="default",
                    workspace_root=root,
                ).read_text(".git/config", max_bytes=64)

            moved = outside / "moved-cwd"

            def swap_cwd(event: str, _path: str) -> None:
                if event == "shell_cwd_opened":
                    cwd.rename(moved)
                    cwd.symlink_to(outside, target_is_directory=True)

            filesystem = ConfinedWorkspaceFilesystem(
                workspace_id="default",
                workspace_root=root,
                race_hook=swap_cwd,
            )
            with self.assertRaises(RuntimeToolError):
                filesystem.open_shell_cwd("cwd")


if __name__ == "__main__":
    unittest.main()
