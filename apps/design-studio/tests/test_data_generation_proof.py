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
MODEL_PATH = ROOT / "apps/design-studio/service/opendesign_generation_model.py"
ADR_PATH = ROOT / "docs/architecture/design_studio_data_generations.md"
OLD_RUNTIME = "a" * 64
NEW_RUNTIME = "b" * 64
OLD_WEB = "c" * 64
NEW_WEB = "d" * 64
ALT_WEB = "e" * 64
VERIFIED_RUNTIME = {OLD_RUNTIME: "0.10.1", NEW_RUNTIME: "0.16.1"}
VERIFIED_WEB = {
    OLD_WEB: {
        "od_version": "0.10.1",
        "compatible_runtime_artifact_sha256": [OLD_RUNTIME],
    },
    NEW_WEB: {
        "od_version": "0.16.1",
        "compatible_runtime_artifact_sha256": [NEW_RUNTIME],
    },
    ALT_WEB: {
        "od_version": "0.16.1",
        "compatible_runtime_artifact_sha256": [NEW_RUNTIME],
    },
}


def _generation_modules():
    model_spec = importlib.util.spec_from_file_location("opendesign_generation_model", MODEL_PATH)
    assert model_spec is not None and model_spec.loader is not None
    model = importlib.util.module_from_spec(model_spec)
    sys.modules[model_spec.name] = model
    model_spec.loader.exec_module(model)
    spec = importlib.util.spec_from_file_location("opendesign_generation_control", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return model, module


class DesignStudioDataGenerationProofTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="maverick-control-v2-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "opendesign"
        self.root.mkdir()
        for name in ("migrations", "backups", "web-activations"):
            (self.root / name).mkdir()
        self.model, self.module = _generation_modules()
        self.old = self.model.LaunchSelection(OLD_RUNTIME, OLD_WEB, "0.10.1", "gen_old")
        self.new = self.model.LaunchSelection(NEW_RUNTIME, NEW_WEB, "0.16.1", "gen_new")
        self.alt_web = self.model.LaunchSelection(NEW_RUNTIME, ALT_WEB, "0.16.1", "gen_new")
        self._make_generation(self.old, "old bytes")
        self._make_generation(self.new, "forward migrated bytes")

    def test_release_cutover_and_rollback_keep_complete_selections(self) -> None:
        self._write_control(self._initial_control())
        old_bytes = self._marker(self.old).read_bytes()
        self._write_migration("migration_001", self.old, self.new, "prepared")
        cutover = self._release_control(self.new, self.old, "migration_001")
        self._write_control(cutover)
        self._write_migration("migration_001", self.old, self.new, "cutover_committed")
        loaded = self._load()
        self.assertEqual(loaded.active, self.new)
        self.assertEqual(loaded.previous_release, self.old)
        self.assertIsNone(loaded.previous_web)
        self.assertEqual(self._marker(self.old).read_bytes(), old_bytes)

        self._write_migration("migration_rollback_001", self.new, self.old, "prepared")
        rollback = self._release_control(self.old, self.new, "migration_rollback_001")
        self._write_control(rollback)
        self._write_migration("migration_rollback_001", self.new, self.old, "cutover_committed")
        recovered = self._recover()
        self.assertEqual(recovered.control.active, self.old)
        self.assertEqual(recovered.control.previous_release, self.new)
        self.assertEqual(self._marker(self.new).read_text(encoding="utf-8"), "forward migrated bytes")

    def test_web_only_cutover_and_rollback_do_not_mutate_runtime_data_or_migration_journal(self) -> None:
        self._write_migration("migration_001", self.old, self.new, "cutover_committed")
        release_control = self._release_control(self.new, self.old, "migration_001")
        self._write_control(release_control)
        data_before = self._marker(self.new).read_bytes()
        migration_before = (self.root / "migrations/migration_001.json").read_bytes()
        generation_inventory = sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob("*"))

        self._write_web("web_001", self.new, self.alt_web, "prepared")
        cutover = self.model.GenerationControl(
            active=self.alt_web,
            previous_release=self.old,
            previous_web=self.new,
            migration_id="migration_001",
            web_activation_id="web_001",
            updated_at="2026-08-12T15:00:00Z",
        )
        self._write_control(cutover)
        self._write_web("web_001", self.new, self.alt_web, "ready_committed")
        loaded = self._load()
        self.assertEqual(loaded.active.web_overlay_sha256, ALT_WEB)
        self.assertEqual(loaded.previous_web.web_overlay_sha256, NEW_WEB)

        self._write_web("web_rollback_001", self.alt_web, self.new, "prepared")
        rollback = self.model.GenerationControl(
            active=self.new,
            previous_release=self.old,
            previous_web=self.alt_web,
            migration_id="migration_001",
            web_activation_id="web_rollback_001",
            updated_at="2026-08-12T15:01:00Z",
        )
        self._write_control(rollback)
        self._write_web(
            "web_rollback_001",
            self.alt_web,
            self.new,
            "ready_committed",
        )
        self.assertEqual(self._load().active, self.new)
        self.assertEqual(self._marker(self.new).read_bytes(), data_before)
        self.assertEqual((self.root / "migrations/migration_001.json").read_bytes(), migration_before)
        after_inventory = sorted(
            path.relative_to(self.root).as_posix()
            for path in self.root.rglob("*")
            if not path.as_posix().startswith((self.root / "web-activations").as_posix())
        )
        before_without_web = [path for path in generation_inventory if not path.startswith("web-activations")]
        self.assertEqual(after_inventory, before_without_web)

    def test_web_crash_recovery_reports_readiness_pending_without_guessing(self) -> None:
        self._write_control(self.model.GenerationControl(
            active=self.new,
            previous_release=None,
            previous_web=None,
            migration_id=None,
            web_activation_id=None,
            updated_at="2026-08-12T15:00:00Z",
        ))
        self._write_web("web_crash", self.new, self.alt_web, "prepared")
        cutover = self.model.GenerationControl(
            active=self.alt_web,
            previous_release=None,
            previous_web=self.new,
            migration_id=None,
            web_activation_id="web_crash",
            updated_at="2026-08-12T15:01:00Z",
        )
        with patch.object(self.module, "_fsync_directory", side_effect=OSError("after replace")):
            with self.assertRaisesRegex(OSError, "after replace"):
                self._write_control(cutover)
        recovered = self._recover()
        self.assertEqual(recovered.control.active, self.alt_web)
        self.assertIn(
            "web_crash:activation_committed_readiness_pending",
            recovered.web_reconciliations,
        )

    def test_crash_before_release_replace_keeps_old_selection(self) -> None:
        self._write_control(self._initial_control())
        self._write_migration("migration_001", self.old, self.new, "prepared")
        with patch.object(self.module.os, "replace", side_effect=OSError("before replace")):
            with self.assertRaisesRegex(OSError, "before replace"):
                self._write_control(self._release_control(self.new, self.old, "migration_001"))
        recovered = self._recover()
        self.assertEqual(recovered.control.active, self.old)
        self.assertIn("migration_001:prepared_before_cutover", recovered.migration_reconciliations)

    def test_strict_schema_rejects_v1_unknown_duplicate_and_incompatible_overlay(self) -> None:
        self._write_control(self._initial_control())
        path = self.root / "control.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["schema_version"] = "1"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(self.model.GenerationControlError, "unsupported"):
            self._load()

        self._write_control(self._initial_control())
        raw = path.read_text(encoding="utf-8")
        path.write_text(raw.replace('"schema_version":"2"', '"schema_version":"2","schema_version":"2"'), encoding="utf-8")
        with self.assertRaisesRegex(self.model.GenerationControlError, "duplicate"):
            self._load()

        bad = self.model.LaunchSelection(OLD_RUNTIME, NEW_WEB, "0.10.1", "gen_old")
        control = self.model.GenerationControl(bad, None, None, None, None, "2026-08-12T15:00:00Z")
        with self.assertRaisesRegex(self.model.GenerationControlError, "version|incompatible"):
            self._write_control(control)

    def test_control_generation_and_web_journal_symlinks_fail_closed(self) -> None:
        outside = Path(self.temp.name) / "outside.json"
        outside.write_text("{}", encoding="utf-8")
        (self.root / "control.json").symlink_to(outside)
        with self.assertRaisesRegex(self.model.GenerationControlError, "regular file"):
            self._load()
        (self.root / "control.json").unlink()

        self._write_control(self._initial_control())
        generation = self._marker(self.old).parent.parent
        self._marker(self.old).unlink()
        self._marker(self.old).parent.rmdir()
        generation.rmdir()
        generation.symlink_to(Path(self.temp.name))
        with self.assertRaisesRegex(self.model.GenerationControlError, "real directory"):
            self._load()

    def test_concurrent_readers_observe_only_complete_v2_documents(self) -> None:
        self._write_control(self.model.GenerationControl(self.new, None, None, None, None, "2026-08-12T15:00:00Z"))
        self._write_web("web_one", self.new, self.alt_web, "prepared")
        self._write_web("web_two", self.alt_web, self.new, "prepared")
        first = self.model.GenerationControl(self.alt_web, None, self.new, None, "web_one", "2026-08-12T15:01:00Z")
        second = self.model.GenerationControl(self.new, None, self.alt_web, None, "web_two", "2026-08-12T15:02:00Z")
        failures: list[BaseException] = []

        def writer() -> None:
            try:
                for index in range(30):
                    self._write_control(first if index % 2 == 0 else second)
            except BaseException as exc:
                failures.append(exc)

        thread = threading.Thread(target=writer)
        thread.start()
        while thread.is_alive():
            try:
                observed = self._load()
                self.assertIn(observed.active, {self.new, self.alt_web})
                if observed.previous_web is not None:
                    self.assertTrue(observed.active.same_runtime_and_data(observed.previous_web))
            except BaseException as exc:
                failures.append(exc)
                break
        thread.join()
        self.assertEqual(failures, [])

    def test_adr_freezes_v2_web_journal_crash_retention_and_rollbacks(self) -> None:
        adr = ADR_PATH.read_text(encoding="utf-8")
        for text in (
            "## Control schema v2",
            "## Migration journal",
            "## Cutover protocol",
            "## Web-only activation journal and protocol",
            "## Crash recovery",
            "After directory fsync, before journal commit",
            "## Rollback",
            "## Retention",
            "previous_release",
            "previous_web",
            "OD_STATIC_DIR",
        ):
            self.assertIn(text, adr)

    def _make_generation(self, selection, marker: str) -> None:
        data = self.root / "instances" / selection.data_generation / "data"
        data.mkdir(parents=True)
        (data / "marker.txt").write_text(marker, encoding="utf-8")

    def _marker(self, selection) -> Path:
        return self.root / "instances" / selection.data_generation / "data/marker.txt"

    def _initial_control(self):
        return self.model.GenerationControl(self.old, None, None, None, None, "2026-08-12T14:00:00Z")

    def _release_control(self, active, previous, migration_id: str):
        return self.model.GenerationControl(
            active,
            previous,
            None,
            migration_id,
            None,
            "2026-08-12T14:10:00Z",
        )

    def _write_control(self, control) -> None:
        self.module.write_generation_control(
            self.root,
            control,
            verified_artifacts=VERIFIED_RUNTIME,
            verified_overlays=VERIFIED_WEB,
        )

    def _load(self):
        return self.module.load_generation_control(
            self.root,
            verified_artifacts=VERIFIED_RUNTIME,
            verified_overlays=VERIFIED_WEB,
        )

    def _recover(self):
        return self.module.recover_generation_control(
            self.root,
            verified_artifacts=VERIFIED_RUNTIME,
            verified_overlays=VERIFIED_WEB,
        )

    def _write_migration(self, migration_id, source, target, state: str) -> None:
        snapshot = self.root / "backups" / migration_id
        snapshot.mkdir(exist_ok=True)
        self.module.write_migration_journal(
            self.root,
            self.model.MigrationJournal(
                migration_id,
                state,
                source,
                target,
                f"backups/{migration_id}",
                {},
                "2026-08-12T14:00:00Z",
                "2026-08-12T14:00:00Z",
            ),
            verified_artifacts=VERIFIED_RUNTIME,
            verified_overlays=VERIFIED_WEB,
        )

    def _write_web(self, activation_id, source, target, state: str, error: str | None = None) -> None:
        self.module.write_web_activation_journal(
            self.root,
            self.model.WebActivationJournal(
                activation_id,
                state,
                source,
                target,
                {"ready": state == "ready_committed"},
                error,
                "2026-08-12T14:00:00Z",
                "2026-08-12T14:00:00Z",
            ),
            verified_artifacts=VERIFIED_RUNTIME,
            verified_overlays=VERIFIED_WEB,
        )


if __name__ == "__main__":
    unittest.main()
