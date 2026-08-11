from __future__ import annotations

import importlib.util
import json
import stat
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
SERVICE_ROOT = ROOT / "apps/design-studio/service"
MODULE_PATH = SERVICE_ROOT / "opendesign_migration.py"
ACCEPTANCE_PATH = SERVICE_ROOT / "opendesign_migration_acceptance_0_16_1.json"
OLD_DIGEST = "a" * 64
_BUNDLE_MANIFEST = json.loads(
    (SERVICE_ROOT / "opendesign_bundle.json").read_text(encoding="utf-8")
)
NEW_DIGEST = _BUNDLE_MANIFEST["artifact"]["assets"]["linux-x86_64"]["sha256"]
VERIFIED = {OLD_DIGEST: "0.10.1", NEW_DIGEST: "0.16.1"}
LEGACY_ID = "design_0123456789ab"


def _load_module(name: str, path: Path):
    sys.path.insert(0, str(SERVICE_ROOT))
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeRuntime:
    def __init__(self) -> None:
        self.events: list[object] = []
        self.uploads: list[dict[str, object]] = []
        self.fail_create = False
        self.fail_health = False

    def freeze_mutations(self) -> None:
        self.events.append("freeze")

    def unfreeze_mutations(self) -> None:
        self.events.append("unfreeze")

    def drain_or_cancel_runs(self) -> None:
        self.events.append("drain")

    def stop_sidecar(self) -> None:
        self.events.append("stop")

    def prove_sidecar_stopped(self, data_dir: Path) -> None:
        self.events.append(("stopped", data_dir.name))

    def start_sidecar(self, triple, data_dir: Path, *, staging: bool) -> None:
        self.events.append(("start", triple.data_generation, data_dir.name, staging))

    def health_check(self) -> None:
        self.events.append("health")
        if self.fail_health:
            raise ValueError("injected staging health failure")

    def verify_database(self) -> None:
        self.events.append("db-verify")

    def list_project_ids(self) -> list[str]:
        self.events.append("list-projects")
        return ["od_existing"]

    def smoke_project(self, project_id: str) -> None:
        self.events.append(("smoke", project_id))

    def create_legacy_project(self, project, *, idempotency_key: str) -> str:
        self.events.append(("create", project["id"], idempotency_key))
        if self.fail_create:
            raise ValueError("injected API failure with /private/path")
        return "od_migrated_01"

    def upload_legacy_import(
        self,
        project_id: str,
        *,
        name: str,
        media_type: str,
        content: bytes,
        sha256: str,
    ) -> None:
        self.uploads.append(
            {
                "project_id": project_id,
                "name": name,
                "media_type": media_type,
                "content": content,
                "sha256": sha256,
            }
        )


class OpenDesignMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.model = _load_module(
            "opendesign_generation_model",
            SERVICE_ROOT / "opendesign_generation_model.py",
        )
        self.control_module = _load_module(
            "opendesign_generation_control",
            SERVICE_ROOT / "opendesign_generation_control.py",
        )
        self.runtime_module = _load_module(
            "opendesign_migration_runtime",
            SERVICE_ROOT / "opendesign_migration_runtime.py",
        )
        self.files = _load_module(
            "opendesign_migration_files",
            SERVICE_ROOT / "opendesign_migration_files.py",
        )
        _load_module(
            "opendesign_migration_legacy",
            SERVICE_ROOT / "opendesign_migration_legacy.py",
        )
        self.module = _load_module("opendesign_migration", MODULE_PATH)
        self.oci_runtime = _load_module(
            "opendesign_migration_oci_runtime",
            SERVICE_ROOT / "opendesign_migration_oci_runtime.py",
        )
        self.temp = tempfile.TemporaryDirectory(prefix="maverick-wp6-")
        self.addCleanup(self.temp.cleanup)
        self.app_data = Path(self.temp.name) / "design-studio"
        self.root = self.app_data / "opendesign"
        for path in (
            self.root,
            self.root / "instances",
            self.root / "backups",
            self.root / "migrations",
        ):
            path.mkdir(parents=True, exist_ok=True)
        self.files.mark_controlled_copy(self.root)
        self.old = self.model.GenerationTriple(OLD_DIGEST, "0.10.1", "gen_old")
        self.new = self.model.GenerationTriple(NEW_DIGEST, "0.16.1", "gen_new")
        old_data = self.root / "instances" / "gen_old" / "data"
        old_data.mkdir(parents=True)
        (old_data / "legacy.db").write_bytes(b"old generation bytes")
        initial = self.model.GenerationControl(
            active=self.old,
            previous=None,
            migration_id=None,
            updated_at="2026-08-04T12:00:00Z",
        )
        self.control_module.write_generation_control(self.root, initial, verified_artifacts=VERIFIED)
        imported = self.app_data / "imports" / LEGACY_ID / "import_001" / "brief.txt"
        imported.parent.mkdir(parents=True)
        imported.write_bytes(b"legacy import bytes")
        self.state_path = self.app_data / "state.json"
        self.state_path.write_text(
            json.dumps(
                {
                    "schema_version": "1",
                    "projects": [
                        {
                            "id": LEGACY_ID,
                            "name": "Legacy dashboard",
                            "prompt": "Make it clear",
                            "imports": [
                                {
                                    "status": "imported",
                                    "name": "brief.txt",
                                    "media_type": "text/plain",
                                    "app_data_path": imported.relative_to(self.app_data).as_posix(),
                                }
                            ],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        self.runtime = FakeRuntime()
        self.timestamps = iter(
            f"2026-08-04T12:00:{second:02d}Z" for second in range(60)
        )

    def _now(self) -> str:
        return next(self.timestamps)

    def _migrate(self):
        return self.module.migrate_controlled_copy(
            self.root,
            legacy_state_path=self.state_path,
            target=self.new,
            migration_id="migration_fixture_001",
            verified_artifacts=VERIFIED,
            runtime=self.runtime,
            now=self._now,
            minimum_free_bytes=0,
        )

    def test_forward_migration_uses_api_mapping_and_atomic_bundle_data_cutover(self) -> None:
        old_bytes = (self.root / "instances" / "gen_old" / "data" / "legacy.db").read_bytes()

        outcome = self._migrate()

        self.assertEqual(outcome.control.active, self.new)
        self.assertEqual(outcome.control.previous, self.old)
        self.assertEqual(outcome.migrated_projects, 1)
        self.assertEqual(outcome.migrated_imports, 1)
        self.assertEqual(
            (self.root / "instances" / "gen_old" / "data" / "legacy.db").read_bytes(),
            old_bytes,
        )
        self.assertEqual(
            (self.root / "instances" / "gen_new" / "data" / "legacy.db").read_bytes(),
            old_bytes,
        )
        mapping = json.loads((self.root / "legacy-project-map.json").read_text(encoding="utf-8"))
        self.assertEqual(mapping["mappings"][0]["legacy_project_id"], LEGACY_ID)
        self.assertEqual(mapping["mappings"][0]["od_project_id"], "od_migrated_01")
        self.assertEqual(self.runtime.uploads[0]["content"], b"legacy import bytes")
        self.assertFalse(any(isinstance(value, Path) for value in self.runtime.uploads[0].values()))
        journal = self.control_module.load_migration_journal(
            self.root,
            "migration_fixture_001",
            verified_artifacts=VERIFIED,
        )
        self.assertEqual(journal.state, "cutover_committed")
        self.assertEqual(journal.checks["pre_migration_health"], "pass")
        self.assertEqual(journal.checks["pre_migration_staging_project_count"], 1)
        self.assertEqual(journal.checks["post_migration_health"], "pass")
        self.assertEqual(journal.checks["post_migration_staging_project_count"], 1)
        self.assertEqual(self.state_path.stat().st_mode & 0o777, stat.S_IRUSR)
        self.assertIn(("start", "gen_new", "data", True), self.runtime.events)
        self.assertIn(("start", "gen_new", "data", False), self.runtime.events)
        self.assertEqual(self.runtime.events[-1], "unfreeze")

    def test_api_failure_keeps_old_control_and_redacts_error_details(self) -> None:
        self.runtime.fail_create = True

        with self.assertRaisesRegex(self.runtime_module.MigrationError, "ValueError") as raised:
            self._migrate()

        self.assertNotIn("private/path", str(raised.exception))
        control = self.control_module.load_generation_control(self.root, verified_artifacts=VERIFIED)
        self.assertEqual(control.active, self.old)
        self.assertFalse((self.root / "legacy-project-map.json").exists())
        self.assertFalse((self.root / "instances" / "gen_new").exists())
        self.assertFalse((self.root / "backups" / "migration_fixture_001").exists())
        self.assertEqual(self.runtime.events[-1], "unfreeze")

    def test_bundle_upgrade_clones_validates_and_retains_an_atomic_rollback_pair(self) -> None:
        outcome = self.module.upgrade_controlled_copy(
            self.root,
            target=self.new,
            migration_id="migration_bundle_upgrade_001",
            verified_artifacts=VERIFIED,
            runtime=self.runtime,
            now=self._now,
            minimum_free_bytes=0,
        )

        self.assertEqual(outcome.control.active, self.new)
        self.assertEqual(outcome.control.previous, self.old)
        self.assertEqual(outcome.project_count, 1)
        self.assertEqual(
            (self.root / "instances/gen_new/data/legacy.db").read_bytes(),
            b"old generation bytes",
        )
        journal = self.control_module.load_migration_journal(
            self.root,
            "migration_bundle_upgrade_001",
            verified_artifacts=VERIFIED,
        )
        self.assertEqual(journal.state, "cutover_committed")
        self.assertEqual(journal.checks["upgrade_kind"], "bundle_controlled_copy")
        self.assertEqual(journal.checks["pre_cutover_health"], "pass")
        self.assertTrue((self.root / "backups/migration_bundle_upgrade_001/data/legacy.db").is_file())
        self.assertFalse((self.root / "legacy-project-map.json").exists())
        self.assertIn(("start", "gen_new", "data", True), self.runtime.events)
        self.assertIn(("start", "gen_new", "data", False), self.runtime.events)

    def test_bundle_upgrade_staging_failure_preserves_source_and_removes_partial_copies(self) -> None:
        self.runtime.fail_health = True

        with self.assertRaisesRegex(self.runtime_module.MigrationError, "ValueError"):
            self.module.upgrade_controlled_copy(
                self.root,
                target=self.new,
                migration_id="migration_bundle_upgrade_failure",
                verified_artifacts=VERIFIED,
                runtime=self.runtime,
                now=self._now,
                minimum_free_bytes=0,
            )

        control = self.control_module.load_generation_control(self.root, verified_artifacts=VERIFIED)
        self.assertEqual(control.active, self.old)
        self.assertFalse((self.root / "instances/gen_new").exists())
        self.assertFalse((self.root / "backups/migration_bundle_upgrade_failure").exists())
        self.assertEqual(
            (self.root / "instances/gen_old/data/legacy.db").read_bytes(),
            b"old generation bytes",
        )

    def test_recovery_finishes_journal_after_crash_between_cutover_and_commit(self) -> None:
        original_write = self.module.write_migration_journal
        calls = 0

        def fail_second_write(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected journal commit crash")
            return original_write(*args, **kwargs)

        with patch.object(self.module, "write_migration_journal", side_effect=fail_second_write):
            with self.assertRaisesRegex(self.runtime_module.MigrationError, "OSError"):
                self._migrate()

        cutover = self.control_module.load_generation_control(self.root, verified_artifacts=VERIFIED)
        self.assertEqual(cutover.active, self.new)
        pending = self.control_module.load_migration_journal(
            self.root,
            "migration_fixture_001",
            verified_artifacts=VERIFIED,
        )
        self.assertEqual(pending.state, "prepared")

        recovery_runtime = FakeRuntime()
        recovered = self.module.recover_controlled_copy(
            self.root,
            verified_artifacts=VERIFIED,
            runtime=recovery_runtime,
            now=self._now,
        )

        self.assertTrue(recovered.journal_completed)
        committed = self.control_module.load_migration_journal(
            self.root,
            "migration_fixture_001",
            verified_artifacts=VERIFIED,
        )
        self.assertEqual(committed.state, "cutover_committed")
        self.assertEqual(self.state_path.stat().st_mode & 0o777, stat.S_IRUSR)
        self.assertIn(("start", "gen_new", "data", False), recovery_runtime.events)

    def test_rollback_reactivates_previous_pair_without_touching_forward_data(self) -> None:
        self._migrate()
        forward = self.root / "instances" / "gen_new" / "data" / "legacy.db"
        forward.write_bytes(b"forward-only bytes")
        rollback_runtime = FakeRuntime()

        rollback = self.module.rollback_controlled_copy(
            self.root,
            rollback_id="migration_rollback_001",
            verified_artifacts=VERIFIED,
            runtime=rollback_runtime,
            now=self._now,
        )

        self.assertEqual(rollback.active, self.old)
        self.assertEqual(rollback.previous, self.new)
        self.assertEqual(forward.read_bytes(), b"forward-only bytes")
        self.assertIn(("start", "gen_old", "data", False), rollback_runtime.events)
        self.assertIn("health", rollback_runtime.events)
        self.assertIn("db-verify", rollback_runtime.events)
        self.assertIn(("smoke", "od_existing"), rollback_runtime.events)

    def test_real_migration_acceptance_binds_the_pinned_artifact_without_workspace_data(self) -> None:
        acceptance = json.loads(ACCEPTANCE_PATH.read_text(encoding="utf-8"))
        forward = acceptance["forward_fixture_migration"]
        self.assertEqual(acceptance["schema_version"], "1")
        self.assertEqual(forward["source"]["od_version"], "0.10.1")
        self.assertEqual(forward["target"]["artifact_sha256"], NEW_DIGEST)
        self.assertTrue(forward["target"]["real_materialized_daemon"])
        self.assertEqual(forward["source"]["tree_sha256_before"], forward["source"]["tree_sha256_after"])
        self.assertEqual(forward["api_import_read_back"], "byte_identical")
        self.assertTrue(acceptance["rollback"]["forward_generation_preserved"])
        self.assertEqual(
            acceptance["rollback"]["real_round_trip_artifact_sha256"],
            NEW_DIGEST,
        )
        self.assertFalse(acceptance["workspace_data_migrated"])

    def test_retention_cleanup_rejects_references_and_deletes_only_explicit_orphan(self) -> None:
        orphan = self.root / "instances" / "gen_orphan" / "data"
        orphan.mkdir(parents=True)
        (orphan / "marker").write_text("orphan", encoding="utf-8")

        with self.assertRaisesRegex(self.runtime_module.MigrationError, "still referenced"):
            self.module.cleanup_unreferenced_generation(
                self.root,
                generation_id="gen_old",
                verified_artifacts=VERIFIED,
                runtime=self.runtime,
                retention_expired=True,
            )
        with self.assertRaisesRegex(self.runtime_module.MigrationError, "not expired"):
            self.module.cleanup_unreferenced_generation(
                self.root,
                generation_id="gen_orphan",
                verified_artifacts=VERIFIED,
                runtime=self.runtime,
                retention_expired=False,
            )

        self.module.cleanup_unreferenced_generation(
            self.root,
            generation_id="gen_orphan",
            verified_artifacts=VERIFIED,
            runtime=self.runtime,
            retention_expired=True,
        )

        self.assertFalse(orphan.parent.exists())
        self.assertTrue(self.root.exists())

    def test_unmarked_root_and_symlinked_legacy_input_fail_closed(self) -> None:
        marker = self.root / self.files.CONTROLLED_COPY_MARKER
        marker.unlink()
        with self.assertRaisesRegex(self.runtime_module.MigrationError, "controlled input|marker"):
            self._migrate()

        self.files.atomic_write_json(
            marker,
            {"schema_version": "1", "scope": "fixture-or-controlled-copy"},
        )
        outside = Path(self.temp.name) / "outside.json"
        outside.write_text('{"projects":[]}', encoding="utf-8")
        self.state_path.unlink()
        self.state_path.symlink_to(outside)
        with self.assertRaisesRegex(self.runtime_module.MigrationError, "failed: MigrationError"):
            self._migrate()
        self.assertFalse((self.root / "backups" / "migration_fixture_001").exists())
        self.assertFalse((self.root / "instances" / "gen_new").exists())

    def test_symlink_in_source_generation_is_rejected_without_partial_copies(self) -> None:
        outside = Path(self.temp.name) / "outside.db"
        outside.write_bytes(b"outside")
        source_link = self.root / "instances" / "gen_old" / "data" / "escape.db"
        source_link.symlink_to(outside)

        with self.assertRaisesRegex(self.runtime_module.MigrationError, "MigrationError"):
            self._migrate()

        self.assertFalse((self.root / "backups" / "migration_fixture_001").exists())
        self.assertFalse((self.root / "instances" / "gen_new").exists())

    def test_real_runtime_log_rejects_symlinks_and_uses_a_regular_file(self) -> None:
        log_root = Path(self.temp.name) / "log-proof"
        log_root.mkdir()
        outside = Path(self.temp.name) / "outside.log"
        outside.write_bytes(b"outside")
        log_path = log_root / "runtime.log"
        log_path.symlink_to(outside)
        with self.assertRaisesRegex(self.runtime_module.MigrationError, "unsafe"):
            self.oci_runtime._open_append_log(log_path)
        self.assertEqual(outside.read_bytes(), b"outside")
        log_path.unlink()
        with self.oci_runtime._open_append_log(log_path) as handle:
            handle.write(b"bounded runtime evidence\n")
        self.assertEqual(log_path.read_bytes(), b"bounded runtime evidence\n")


if __name__ == "__main__":
    unittest.main()
