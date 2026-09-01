from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import tempfile
import unittest

from core.runtime.confined_filesystem import (
    ConfinedWorkspaceFilesystem,
    FilesystemResourceObservation,
)
from core.runtime.tool_errors import RuntimeToolError
from core.workspaces.data_governance import (
    WorkspaceResourceClassification,
    resource_classification_for_observation,
)


NOW = datetime(2026, 8, 26, tzinfo=UTC)


class ConfinedWorkspaceFilesystemSnapshotTest(unittest.TestCase):
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
