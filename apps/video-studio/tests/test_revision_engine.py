"""Persistent revision engine, concurrency, recovery, and interchange tests."""

from __future__ import annotations

from copy import deepcopy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
import threading
import unittest


APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT / "backend"))

from projects import ProjectError, ProjectService  # noqa: E402


FIXTURE = APP_ROOT / "tests" / "fixtures" / "project-ir-v1-golden.json"
STAMP = "2026-08-10T12:00:00.000Z"


def golden() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def service(root: str | Path, workspace_id: str = "workspace-test") -> ProjectService:
    return ProjectService(root, workspace_id=workspace_id, clock=lambda: STAMP, id_factory=lambda: "generated")


def edit_batch(
    revision_id: str,
    *,
    batch_id: str,
    name: str = "Renamed",
    workspace_id: str = "workspace-test",
    project_id: str = "project-golden",
) -> dict:
    return {
        "workspace_id": workspace_id,
        "project_id": project_id,
        "base_revision_id": revision_id,
        "operation_batch_id": batch_id,
        "preconditions": [{"type": "head_is", "revision_id": revision_id}],
        "actor": {"kind": "user", "id": "editor-1"},
        "operations": [{"type": "project.rename", "name": name}],
        "autosave": {"enabled": True, "reason": "typing"},
        "metadata": {"message": "Rename"},
    }


def history_batch(revision_id: str, batch_id: str, direction: str) -> dict:
    value = edit_batch(revision_id, batch_id=batch_id)
    value["operations"] = [{"type": f"history.{direction}"}]
    value["autosave"] = {"enabled": False, "reason": direction}
    return value


class RevisionEngineTest(unittest.TestCase):
    def test_create_list_get_digest_and_revision_compare(self) -> None:
        with TemporaryDirectory() as temp_dir:
            application = service(temp_dir)
            created = application.create_project(
                name="Golden timeline",
                project_id="project-golden",
                project_ir=golden(),
                actor={"kind": "user", "id": "editor-1"},
            )
            renamed = application.apply_operations(
                edit_batch(created["head_revision_id"], batch_id="batch-rename")
            )

            create_events = [
                event
                for event in application.pending_outbox()
                if event["event_type"] in {"project.created", "project.revision.created"}
            ]
            self.assertEqual({event["resource"] for event in create_events}, {"projects", "revisions"})
            self.assertEqual(application.list_projects()[0]["head_revision_id"], renamed["revision_id"])
            self.assertEqual(application.get_revision("project-golden", renamed["revision_id"])["digest"], renamed["digest"])
            comparison = application.compare_revisions(
                "project-golden", created["head_revision_id"], renamed["revision_id"]
            )
            self.assertEqual(comparison["change_count"], 1)
            self.assertEqual(comparison["changes"][0]["path"], "/metadata/name")

    def test_idempotency_stale_conflict_and_batch_id_collision(self) -> None:
        with TemporaryDirectory() as temp_dir:
            application = service(temp_dir)
            created = application.create_project(name="Golden timeline", project_id="project-golden", project_ir=golden())
            request = edit_batch(created["head_revision_id"], batch_id="batch-one")
            first = application.apply_operations(request)
            self.assertEqual(application.apply_operations(request), first)

            collision = edit_batch(created["head_revision_id"], batch_id="batch-one", name="Different")
            with self.assertRaises(ProjectError) as reused:
                application.apply_operations(collision)
            self.assertEqual(reused.exception.code, "operation_batch_id_conflict")

            with self.assertRaises(ProjectError) as stale:
                application.apply_operations(edit_batch(created["head_revision_id"], batch_id="batch-stale"))
            self.assertEqual(stale.exception.code, "stale_revision_conflict")
            self.assertEqual(stale.exception.details["actual_revision_id"], first["revision_id"])

            second_project = application.create_project(
                name="Second", project_id="project-second", project_ir=golden()
            )
            scoped = application.apply_operations(
                edit_batch(
                    second_project["head_revision_id"],
                    batch_id="batch-one",
                    name="Second renamed",
                    project_id="project-second",
                )
            )
            self.assertEqual(scoped["project_id"], "project-second")

    def test_concurrent_batches_allow_exactly_one_head_update(self) -> None:
        with TemporaryDirectory() as temp_dir:
            application = service(temp_dir)
            base = application.create_project(name="Golden timeline", project_id="project-golden", project_ir=golden())
            barrier = threading.Barrier(3)
            results: list[str] = []

            def writer(batch_id: str, name: str) -> None:
                barrier.wait()
                try:
                    independent_process = service(temp_dir)
                    independent_process.apply_operations(
                        edit_batch(base["head_revision_id"], batch_id=batch_id, name=name)
                    )
                    results.append("success")
                except ProjectError as error:
                    results.append(error.code)

            threads = [
                threading.Thread(target=writer, args=("batch-a", "Writer A")),
                threading.Thread(target=writer, args=("batch-b", "Writer B")),
            ]
            for thread in threads:
                thread.start()
            barrier.wait()
            for thread in threads:
                thread.join(timeout=10)
            self.assertCountEqual(results, ["success", "stale_revision_conflict"])

    def test_invalid_batch_and_outbox_failure_roll_back_atomically(self) -> None:
        with TemporaryDirectory() as temp_dir:
            application = service(temp_dir)
            created = application.create_project(name="Golden timeline", project_id="project-golden", project_ir=golden())
            before = self._counts(application)
            invalid = edit_batch(created["head_revision_id"], batch_id="batch-invalid")
            invalid["operations"].append({"type": "unsupported.operation"})
            with self.assertRaises(ProjectError):
                application.apply_operations(invalid)
            self.assertEqual(self._counts(application), before)
            self.assertEqual(application.get_project("project-golden")["head_revision_id"], created["head_revision_id"])

            with closing(application.database.connect()) as connection:
                connection.execute(
                    """
                    CREATE TRIGGER reject_revision_event BEFORE INSERT ON project_outbox
                    WHEN NEW.event_type = 'project.revision.changed'
                    BEGIN SELECT RAISE(ABORT, 'outbox rejected'); END
                    """
                )
                connection.commit()
            with self.assertRaises(sqlite3.DatabaseError):
                application.apply_operations(edit_batch(created["head_revision_id"], batch_id="batch-outbox"))
            self.assertEqual(self._counts(application), before)
            self.assertEqual(application.get_project("project-golden")["name"], "Golden timeline")

    def test_undo_redo_autosave_and_recovery_survive_restart(self) -> None:
        with TemporaryDirectory() as temp_dir:
            first_process = service(temp_dir)
            created = first_process.create_project(name="Golden timeline", project_id="project-golden", project_ir=golden())
            edited = first_process.apply_operations(edit_batch(created["head_revision_id"], batch_id="batch-edit"))
            recovered = service(temp_dir)
            undone = recovered.undo(history_batch(edited["revision_id"], "batch-undo", "undo"))
            self.assertEqual(recovered.get_project("project-golden")["name"], "Golden timeline")

            final_process = service(temp_dir)
            redone = final_process.redo(history_batch(undone["revision_id"], "batch-redo", "redo"))
            self.assertEqual(redone["revision_id"], edited["revision_id"])
            self.assertEqual(final_process.get_project("project-golden")["name"], "Renamed")
            with closing(final_process.database.connect(read_only=True)) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM project_autosaves").fetchone()[0], 1)
            self.assertGreaterEqual(len(final_process.pending_outbox()), 5)

    def test_idempotency_and_redo_invalidation_survive_service_restart(self) -> None:
        with TemporaryDirectory() as temp_dir:
            first_process = service(temp_dir)
            created = first_process.create_project(
                name="Golden timeline", project_id="project-golden", project_ir=golden()
            )
            request = edit_batch(created["head_revision_id"], batch_id="batch-replay")
            edited = first_process.apply_operations(request)

            recovered = service(temp_dir)
            self.assertEqual(recovered.apply_operations(request), edited)
            undone = recovered.undo(history_batch(edited["revision_id"], "batch-undo", "undo"))
            replacement = recovered.apply_operations(
                edit_batch(
                    undone["revision_id"],
                    batch_id="batch-replacement",
                    name="Replacement",
                )
            )

            restarted = service(temp_dir)
            with self.assertRaises(ProjectError) as unavailable:
                restarted.redo(history_batch(replacement["revision_id"], "batch-redo", "redo"))
            self.assertEqual(unavailable.exception.code, "redo_unavailable")

    def test_workspace_binding_prevents_reusing_one_store_across_workspaces(self) -> None:
        with TemporaryDirectory() as shared_root, TemporaryDirectory() as other_root:
            workspace_one = service(shared_root, workspace_id="workspace-test")
            workspace_one.create_project(
                name="Golden timeline", project_id="project-golden", project_ir=golden()
            )
            with self.assertRaises(ProjectError) as mismatch:
                service(shared_root, workspace_id="workspace-other")
            self.assertEqual(mismatch.exception.code, "workspace_store_mismatch")

            other_document = golden()
            other_document["metadata"]["workspace_id"] = "workspace-other"
            for asset in other_document["assets"]:
                asset["provenance"]["workspace_id"] = "workspace-other"
            isolated = service(other_root, workspace_id="workspace-other")
            isolated.create_project(
                name="Other", project_id="project-golden", project_ir=other_document
            )
            self.assertEqual(len(workspace_one.list_projects()), 1)
            self.assertEqual(len(isolated.list_projects()), 1)

    def test_duplicate_archive_restore_and_native_round_trip(self) -> None:
        with TemporaryDirectory() as source_root, TemporaryDirectory() as import_root:
            application = service(source_root)
            created = application.create_project(name="Golden timeline", project_id="project-golden", project_ir=golden())
            duplicate = application.duplicate_project(
                "project-golden", name="Copy", project_id="project-copy"
            )
            self.assertEqual(duplicate["project_ir"]["metadata"]["project_id"], "project-copy")
            self.assertNotEqual(duplicate["digest"], created["digest"])
            self.assertIsNotNone(application.archive_project("project-copy")["archived_at"])
            self.assertNotIn("project-copy", {item["project_id"] for item in application.list_projects()})
            self.assertIsNone(application.restore_project("project-copy")["archived_at"])

            exported = application.export_native("project-golden")
            imported = service(import_root).import_native(exported)
            self.assertEqual(imported["digest"], exported["revision"]["digest"])
            self.assertEqual(imported["project_ir"], exported["revision"]["project_ir"])

    def test_import_rejects_tampering_external_workspace_and_path_traversal(self) -> None:
        with TemporaryDirectory() as source_root, TemporaryDirectory() as target_root:
            source = service(source_root)
            source.create_project(name="Golden timeline", project_id="project-golden", project_ir=golden())
            exported = source.export_native("project-golden")
            target = service(target_root)

            arbitrary_path = deepcopy(exported)
            arbitrary_path["path"] = "/tmp/host-project.json"
            with self.assertRaises(ProjectError) as path_field_error:
                target.import_native(arbitrary_path)
            self.assertEqual(path_field_error.exception.code, "native_import_invalid")

            tampered = deepcopy(exported)
            tampered["revision"]["project_ir"]["metadata"]["name"] = "Tampered"
            with self.assertRaises(ProjectError) as digest_error:
                target.import_native(tampered)
            self.assertEqual(digest_error.exception.code, "native_import_digest_mismatch")

            traversal = deepcopy(exported)
            traversal["revision"]["project_ir"]["metadata"]["name"] = "../outside"
            traversal["revision"]["digest"] = _digest(traversal["revision"]["project_ir"])
            with self.assertRaises(ProjectError) as path_error:
                target.import_native(traversal)
            self.assertEqual(path_error.exception.code, "project_ir_invalid")

            other = service(Path(target_root) / "other", workspace_id="workspace-other")
            with self.assertRaises(ProjectError) as workspace_error:
                other.import_native(exported)
            self.assertEqual(workspace_error.exception.code, "project_ir_invalid")

    @staticmethod
    def _counts(application: ProjectService) -> tuple[int, ...]:
        with closing(application.database.connect(read_only=True)) as connection:
            tables = (
                "project_revisions",
                "project_operation_batches",
                "project_autosaves",
                "project_outbox",
            )
            return tuple(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables)


def _digest(value: object) -> str:
    from project_ir.canonical import content_digest

    return content_digest(value)


if __name__ == "__main__":
    unittest.main()
