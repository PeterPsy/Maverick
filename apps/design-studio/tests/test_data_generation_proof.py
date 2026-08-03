from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "apps/design-studio/service/opendesign_generation_control.py"
ADR_PATH = ROOT / "docs/architecture/design_studio_data_generations.md"
OLD_DIGEST = "a" * 64
NEW_DIGEST = "b" * 64
VERIFIED = {OLD_DIGEST: "0.10.1", NEW_DIGEST: "0.16.1"}


def _generation_module():
    spec = importlib.util.spec_from_file_location("opendesign_generation_control", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class DesignStudioDataGenerationProofTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="maverick-g4-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "opendesign"
        self.root.mkdir()
        (self.root / "migrations").mkdir()
        (self.root / "backups").mkdir()
        self.module = _generation_module()
        self.old = self.module.GenerationTriple(OLD_DIGEST, "0.10.1", "gen_old")
        self.new = self.module.GenerationTriple(NEW_DIGEST, "0.16.1", "gen_new")
        self._make_generation(self.old, "old bytes")
        self._make_generation(self.new, "forward migrated bytes")

    def test_atomic_cutover_and_rollback_keep_bundle_data_pairs(self) -> None:
        initial = self._initial_control()
        self.module.write_generation_control(self.root, initial, verified_artifacts=VERIFIED)
        self.assertEqual((self.root / "control.json").stat().st_mode & 0o777, 0o600)
        old_marker = self._marker(self.old).read_bytes()

        self._write_journal("migration_001", self.old, self.new, "prepared")
        cutover = self._cutover_control()
        self.module.write_generation_control(self.root, cutover, verified_artifacts=VERIFIED)
        self._write_journal("migration_001", self.old, self.new, "cutover_committed")
        loaded = self.module.load_generation_control(self.root, verified_artifacts=VERIFIED)
        self.assertEqual(loaded.active, self.new)
        self.assertEqual(loaded.previous, self.old)
        self.assertEqual(self._marker(self.old).read_bytes(), old_marker)

        rollback = self.module.GenerationControl(
            active=self.old,
            previous=self.new,
            migration_id="migration_rollback_001",
            updated_at="2026-08-03T17:20:00Z",
        )
        self._write_journal("migration_rollback_001", self.new, self.old, "prepared")
        self.module.write_generation_control(self.root, rollback, verified_artifacts=VERIFIED)
        self._write_journal("migration_rollback_001", self.new, self.old, "cutover_committed")
        recovered = self.module.recover_generation_control(self.root, verified_artifacts=VERIFIED)
        self.assertEqual(recovered.control.active, self.old)
        self.assertEqual(recovered.active_data_dir, self._marker(self.old).parent)
        self.assertEqual(self._marker(self.new).read_text(encoding="utf-8"), "forward migrated bytes")
        self.assertFalse(any(path.is_symlink() for path in self.root.rglob("*")))
        self.assertIn("migration_001:historical_cutover_committed", recovered.migration_reconciliations)
        self.assertIn("migration_rollback_001:committed", recovered.migration_reconciliations)

    def test_crash_before_replace_keeps_old_control(self) -> None:
        self.module.write_generation_control(self.root, self._initial_control(), verified_artifacts=VERIFIED)
        self._write_journal("migration_001", self.old, self.new, "prepared")
        with patch.object(self.module.os, "replace", side_effect=OSError("injected before replace")):
            with self.assertRaisesRegex(OSError, "injected before replace"):
                self.module.write_generation_control(
                    self.root,
                    self._cutover_control(),
                    verified_artifacts=VERIFIED,
                )

        recovered = self.module.recover_generation_control(self.root, verified_artifacts=VERIFIED)
        self.assertEqual(recovered.control.active, self.old)
        self.assertIn("migration_001:prepared_before_cutover", recovered.migration_reconciliations)
        self.assertFalse(any(path.name.endswith(".tmp") for path in self.root.iterdir()))

    def test_crash_after_replace_recovers_new_control_without_guessing(self) -> None:
        self.module.write_generation_control(self.root, self._initial_control(), verified_artifacts=VERIFIED)
        self._write_journal("migration_001", self.old, self.new, "prepared")
        with patch.object(self.module, "_fsync_directory", side_effect=OSError("injected after replace")):
            with self.assertRaisesRegex(OSError, "injected after replace"):
                self.module.write_generation_control(
                    self.root,
                    self._cutover_control(),
                    verified_artifacts=VERIFIED,
                )

        newest = self.module.GenerationTriple(NEW_DIGEST, "0.16.1", "gen_newest_but_inactive")
        self._make_generation(newest, "must not be selected")
        recovered = self.module.recover_generation_control(self.root, verified_artifacts=VERIFIED)
        self.assertEqual(recovered.control.active, self.new)
        self.assertNotEqual(recovered.control.active, newest)
        self.assertIn("migration_001:replace_committed_journal_pending", recovered.migration_reconciliations)

    def test_recovery_removes_only_strict_stale_temp_and_uses_control(self) -> None:
        self.module.write_generation_control(self.root, self._initial_control(), verified_artifacts=VERIFIED)
        stale = self.root / ".control.json.0123456789abcdef.tmp"
        stale.write_text("partial", encoding="utf-8")
        unrelated = self.root / "control.json.notes.tmp"
        unrelated.write_text("keep", encoding="utf-8")
        journal_stale = self.root / "migrations" / ".migration_ghost.json.0123456789abcdef.tmp"
        journal_stale.write_text("partial", encoding="utf-8")

        recovered = self.module.recover_generation_control(self.root, verified_artifacts=VERIFIED)

        self.assertEqual(recovered.control.active, self.old)
        self.assertEqual(
            recovered.removed_stale_temps,
            (stale.name, f"migrations/{journal_stale.name}"),
        )
        self.assertFalse(stale.exists())
        self.assertFalse(journal_stale.exists())
        self.assertTrue(unrelated.exists())

    def test_parser_rejects_unknown_fields_unverified_artifacts_and_missing_generation(self) -> None:
        self.module.write_generation_control(self.root, self._initial_control(), verified_artifacts=VERIFIED)
        control_path = self.root / "control.json"
        payload = json.loads(control_path.read_text(encoding="utf-8"))
        payload["unexpected"] = True
        control_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(self.module.GenerationControlError, "unknown or missing"):
            self.module.load_generation_control(self.root, verified_artifacts=VERIFIED)

        self.module.write_generation_control(self.root, self._initial_control(), verified_artifacts=VERIFIED)
        with self.assertRaisesRegex(self.module.GenerationControlError, "not verified"):
            self.module.load_generation_control(
                self.root,
                verified_artifacts={NEW_DIGEST: "0.16.1"},
            )

        with self.assertRaisesRegex(self.module.GenerationControlError, "version does not match"):
            self.module.load_generation_control(
                self.root,
                verified_artifacts={OLD_DIGEST: "0.16.1", NEW_DIGEST: "0.16.1"},
            )

        raw = control_path.read_text(encoding="utf-8")
        control_path.write_text(
            raw.replace('"schema_version":"1"', '"schema_version":"1","schema_version":"1"', 1),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(self.module.GenerationControlError, "duplicate JSON field"):
            self.module.load_generation_control(self.root, verified_artifacts=VERIFIED)

        self.module.write_generation_control(self.root, self._initial_control(), verified_artifacts=VERIFIED)
        self._marker(self.old).unlink()
        self._marker(self.old).parent.rmdir()
        with self.assertRaisesRegex(self.module.GenerationControlError, "generation data directory is missing"):
            self.module.load_generation_control(self.root, verified_artifacts=VERIFIED)

    def test_control_and_generation_symlinks_fail_closed(self) -> None:
        outside = Path(self.temp.name) / "outside.json"
        outside.write_text("{}", encoding="utf-8")
        (self.root / "control.json").symlink_to(outside)
        with self.assertRaisesRegex(self.module.GenerationControlError, "regular file"):
            self.module.load_generation_control(self.root, verified_artifacts=VERIFIED)

        (self.root / "control.json").unlink()
        generation_root = self.root / "instances" / self.old.data_generation
        self._marker(self.old).unlink()
        self._marker(self.old).parent.rmdir()
        generation_root.rmdir()
        generation_root.symlink_to(Path(self.temp.name))
        with self.assertRaisesRegex(self.module.GenerationControlError, "real directory"):
            self.module.write_generation_control(
                self.root,
                self._initial_control(),
                verified_artifacts=VERIFIED,
            )

    def test_journal_and_control_must_describe_the_same_atomic_transition(self) -> None:
        self.module.write_generation_control(self.root, self._initial_control(), verified_artifacts=VERIFIED)
        unrelated = self.module.GenerationTriple(NEW_DIGEST, "0.16.1", "gen_unrelated")
        self._make_generation(unrelated, "unrelated")
        self._write_journal("migration_001", self.old, unrelated, "prepared")

        with self.assertRaisesRegex(self.module.GenerationControlError, "inconsistent"):
            self.module.write_generation_control(
                self.root,
                self._cutover_control(),
                verified_artifacts=VERIFIED,
            )
        loaded = self.module.load_generation_control(self.root, verified_artifacts=VERIFIED)
        self.assertEqual(loaded.active, self.old)

    def test_concurrent_readers_observe_only_complete_control_documents(self) -> None:
        self.module.write_generation_control(self.root, self._initial_control(), verified_artifacts=VERIFIED)
        self._write_journal("migration_001", self.old, self.new, "prepared")
        self._write_journal("migration_rollback_001", self.new, self.old, "prepared")
        cutover = self._cutover_control()
        rollback = self.module.GenerationControl(
            active=self.old,
            previous=self.new,
            migration_id="migration_rollback_001",
            updated_at="2026-08-03T17:20:00Z",
        )
        failures: list[BaseException] = []

        def writer() -> None:
            try:
                for index in range(40):
                    control = cutover if index % 2 == 0 else rollback
                    self.module.write_generation_control(
                        self.root,
                        control,
                        verified_artifacts=VERIFIED,
                    )
            except BaseException as exc:  # pragma: no cover - asserted in parent thread
                failures.append(exc)

        thread = threading.Thread(target=writer)
        thread.start()
        while thread.is_alive():
            try:
                observed = self.module.load_generation_control(self.root, verified_artifacts=VERIFIED)
                self.assertIn(observed.active, {self.old, self.new})
                if observed.previous is None:
                    self.assertEqual(observed.active, self.old)
                else:
                    self.assertIn(observed.previous, {self.old, self.new})
                    self.assertNotEqual(observed.active, observed.previous)
            except BaseException as exc:  # pragma: no cover - asserted after join
                failures.append(exc)
                break
        thread.join()
        self.assertEqual(failures, [])

    def test_adr_freezes_schema_journal_crash_matrix_retention_and_rollback(self) -> None:
        adr = ADR_PATH.read_text(encoding="utf-8")

        self.assertIn("## Control schema", adr)
        self.assertIn("## Migration journal", adr)
        self.assertIn("## Cutover protocol", adr)
        self.assertIn("## Crash recovery", adr)
        self.assertIn("After directory fsync, before journal commit", adr)
        self.assertIn("## Rollback", adr)
        self.assertIn("## Retention", adr)
        self.assertIn("default minimum retention is one complete previous", adr)
        self.assertIn("never opened by the older bundle", adr)

    def _make_generation(self, triple, marker: str) -> None:
        data_root = self.root / "instances" / triple.data_generation / "data"
        data_root.mkdir(parents=True)
        (data_root / "marker.txt").write_text(marker, encoding="utf-8")

    def _marker(self, triple) -> Path:
        return self.root / "instances" / triple.data_generation / "data" / "marker.txt"

    def _initial_control(self):
        return self.module.GenerationControl(
            active=self.old,
            previous=None,
            migration_id=None,
            updated_at="2026-08-03T17:00:00Z",
        )

    def _cutover_control(self):
        return self.module.GenerationControl(
            active=self.new,
            previous=self.old,
            migration_id="migration_001",
            updated_at="2026-08-03T17:10:00Z",
        )

    def _write_journal(self, migration_id, source, target, state: str):
        snapshot = self.root / "backups" / migration_id
        snapshot.mkdir(exist_ok=True)
        journal = self.module.MigrationJournal(
            migration_id=migration_id,
            state=state,
            source=source,
            target=target,
            source_snapshot=f"backups/{migration_id}",
            checks={"fixture": "pass"},
            created_at="2026-08-03T17:05:00Z",
            updated_at="2026-08-03T17:06:00Z",
        )
        self.module.write_migration_journal(self.root, journal, verified_artifacts=VERIFIED)
        return journal


if __name__ == "__main__":
    unittest.main()
