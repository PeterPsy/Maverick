"""Recovery and one-writer proofs for the native OpenDesign data cutover."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


APP_ROOT = Path(__file__).resolve().parents[1]
SERVICE_ROOT = APP_ROOT / "service"
sys.path.insert(0, str(SERVICE_ROOT))

from cutover_native_opendesign import _require_writers_stopped  # noqa: E402
from native_cutover_files import NativeCutoverFileError  # noqa: E402
from native_data_cutover import (  # noqa: E402
    NativeDataCutoverError,
    begin_native_writer_activation,
    finish_native_writer_activation,
    perform_native_data_cutover,
)


GENERATION = "gen_legacy_test"
CATEGORIES = (
    "projects",
    "conversations",
    "ordered_messages",
    "design_systems",
    "project_files",
    "artifacts",
    "settings",
    "run_references",
)


def _installation() -> SimpleNamespace:
    release = SimpleNamespace(
        version="0.16.1",
        manifest_digest="sha256:" + "a" * 64,
    )
    return SimpleNamespace(release=release, rootfs_snapshot_sha256="b" * 64)


def _inventory(category_hash: str = "c" * 64) -> dict:
    return {
        "schema_version": "1",
        "kind": "official-opendesign-public-inventory",
        "release": {
            "version": "0.16.1",
            "manifest_digest": "sha256:" + "a" * 64,
            "rootfs_snapshot_sha256": "b" * 64,
        },
        "categories": {
            category: {"count": 1, "sha256": category_hash} for category in CATEGORIES
        },
        "semantic_content_retained": False,
        "private_database_read": False,
    }


def _make_app_root(base: Path) -> tuple[Path, Path]:
    root = base / "design-studio"
    source = root / "opendesign/instances" / GENERATION / "data"
    native = root / "opendesign-native"
    source.mkdir(parents=True)
    native.mkdir(parents=True)
    (source / "app.sqlite").write_bytes(b"canonical-private-db")
    (source / "project-secret.txt").write_text("semantic project secret", encoding="utf-8")
    (source / "launcher-status.json").write_text('{"legacy":true}', encoding="utf-8")
    runtime = source / "maverick-runtime"
    runtime.mkdir()
    (runtime / "correlations.json").write_text('{"thread":"legacy-secret"}', encoding="utf-8")
    (runtime / "conversation-bindings.json").write_text('{"binding":"legacy"}', encoding="utf-8")
    (native / "previous-native.txt").write_text("previous native", encoding="utf-8")
    control = {
        "schema_version": "2",
        "active": {"data_generation": GENERATION},
    }
    files = {
        ".maverick-app.json": {"app_id": "design-studio"},
        "adapter-state.json": {"opendesign_app_config": {"secret": "legacy config"}},
        "state.json": {"projects": [{"name": "legacy project"}]},
        "delegations/state.json": {"delegations": {}},
        "opendesign/control.json": control,
        "opendesign/legacy-project-map.json": {"mappings": {"old": "new"}},
    }
    for relative, payload in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        path.chmod(0o600)
    return root, source


def _force_remove(path: Path) -> None:
    if not path.exists():
        return
    for item in path.rglob("*"):
        try:
            item.chmod(0o700 if item.is_dir() else 0o600)
        except OSError:
            pass
    try:
        path.chmod(0o700)
    except OSError:
        pass
    shutil.rmtree(path, ignore_errors=True)


class NativeDataCutoverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = Path(tempfile.mkdtemp(prefix="native-cutover-test-"))
        self.addCleanup(_force_remove, self.temporary)
        self.root, self.source = _make_app_root(self.temporary)

    def test_cutover_backs_up_certifies_cleans_and_selects_exactly_one_writer(self) -> None:
        calls: list[dict[str, bool]] = []

        def inventory_runner(_installation, *, data_dir: Path, log_path: Path) -> dict:
            calls.append(
                {
                    "runtime_present": (data_dir / "maverick-runtime").exists(),
                    "canonical_present": (data_dir / "project-secret.txt").exists(),
                }
            )
            log_path.write_text("official public API only", encoding="utf-8")
            return _inventory()

        marker = perform_native_data_cutover(
            self.root,
            _installation(),
            inventory_runner=inventory_runner,
            cutover_id="native_test_001",
        )

        self.assertEqual(
            calls,
            [
                {"runtime_present": True, "canonical_present": True},
                {"runtime_present": False, "canonical_present": True},
            ],
        )
        native = self.root / "opendesign-native"
        self.assertEqual((native / "project-secret.txt").read_text(), "semantic project secret")
        self.assertFalse((native / "maverick-runtime").exists())
        self.assertFalse((native / "launcher-status.json").exists())
        self.assertFalse((native / "previous-native.txt").exists())
        self.assertEqual(stat.S_IMODE(native.stat().st_mode), 0o700)
        self.assertEqual(marker["phase"], "prepared")
        self.assertFalse(marker["native_writer_started"])
        self.assertFalse(marker["legacy_writer_enabled"])
        self.assertTrue(marker["rollback_to_legacy_allowed"])
        backup = self.root / marker["backup_directory"]
        self.assertEqual(
            (backup / "canonical-source/project-secret.txt").read_text(),
            "semantic project secret",
        )
        self.assertEqual(
            (backup / "previous-native/previous-native.txt").read_text(),
            "previous native",
        )
        self.assertTrue((backup / "backup-manifest.json").is_file())
        certification = json.loads((backup / "public-api-certification.json").read_text())
        self.assertTrue(certification["matches"])
        self.assertTrue(certification["official_migrations_only"])
        self.assertFalse(certification["private_database_read"])
        self.assertNotIn("semantic project secret", json.dumps(marker))
        self.assertNotIn("semantic project secret", json.dumps(certification))
        self.assertFalse(stat.S_IMODE(backup.stat().st_mode) & 0o222)
        self.assertFalse(stat.S_IMODE(self.source.stat().st_mode) & 0o222)
        for relative in marker["legacy_read_only_files"]:
            self.assertFalse(stat.S_IMODE((self.root / relative).stat().st_mode) & 0o222)
        self.assertTrue(stat.S_IMODE((self.root / ".maverick-app.json").stat().st_mode) & 0o200)
        self.assertTrue(stat.S_IMODE((self.root / "delegations/state.json").stat().st_mode) & 0o200)

        repeated = perform_native_data_cutover(
            self.root,
            _installation(),
            inventory_runner=lambda *_args, **_kwargs: self.fail("inventory repeated"),
        )
        self.assertTrue(repeated["already_cut_over"])

    def test_activation_closes_rollback_before_start_and_never_reopens_legacy(self) -> None:
        marker = perform_native_data_cutover(
            self.root,
            _installation(),
            inventory_runner=lambda *_args, **_kwargs: _inventory(),
            cutover_id="native_test_002",
        )
        activating = begin_native_writer_activation(
            self.root, cutover_id=marker["cutover_id"]
        )
        self.assertEqual(activating["phase"], "activating")
        self.assertTrue(activating["native_writer_started"])
        self.assertFalse(activating["rollback_to_legacy_allowed"])
        failed = finish_native_writer_activation(
            self.root, cutover_id=marker["cutover_id"], ready=False
        )
        self.assertEqual(failed["phase"], "activation_failed")
        self.assertTrue(failed["native_writer_started"])
        self.assertFalse(failed["legacy_writer_enabled"])
        recovered = finish_native_writer_activation(
            self.root, cutover_id=marker["cutover_id"], ready=True
        )
        self.assertEqual(recovered["phase"], "committed")
        self.assertTrue(recovered["native_ready"])

    def test_inventory_mismatch_preserves_native_and_freezes_complete_backup(self) -> None:
        calls = 0

        def mismatch(_installation, *, data_dir: Path, log_path: Path) -> dict:
            nonlocal calls
            calls += 1
            return _inventory("c" * 64 if calls == 1 else "d" * 64)

        with self.assertRaisesRegex(NativeDataCutoverError, "differs in categories"):
            perform_native_data_cutover(
                self.root,
                _installation(),
                inventory_runner=mismatch,
                cutover_id="native_test_mismatch",
            )

        self.assertEqual(
            (self.root / "opendesign-native/previous-native.txt").read_text(),
            "previous native",
        )
        self.assertFalse((self.root / "native-cutover.json").exists())
        backup = self.root / "opendesign-cutover-backups/official-native-native_test_mismatch"
        self.assertTrue(backup.is_dir())
        self.assertFalse(stat.S_IMODE(backup.stat().st_mode) & 0o222)
        self.assertTrue(stat.S_IMODE(self.source.stat().st_mode) & 0o200)

    def test_symlinked_canonical_source_is_rejected(self) -> None:
        real_source = self.source.with_name("real-data")
        self.source.rename(real_source)
        self.source.symlink_to(real_source, target_is_directory=True)

        with self.assertRaisesRegex(NativeCutoverFileError, "real directory"):
            perform_native_data_cutover(
                self.root,
                _installation(),
                inventory_runner=lambda *_args, **_kwargs: _inventory(),
            )

    def test_poisoned_marker_is_rejected_before_activation(self) -> None:
        marker = perform_native_data_cutover(
            self.root,
            _installation(),
            inventory_runner=lambda *_args, **_kwargs: _inventory(),
            cutover_id="native_test_poisoned",
        )
        marker["transcript"] = "must never enter cutover state"
        (self.root / "native-cutover.json").write_text(json.dumps(marker), encoding="utf-8")

        with self.assertRaisesRegex(NativeDataCutoverError, "marker schema"):
            begin_native_writer_activation(self.root, cutover_id="native_test_poisoned")

    def test_operator_refuses_cutover_without_stopped_core_confirmation(self) -> None:
        with self.assertRaisesRegex(NativeDataCutoverError, "confirmation"):
            _require_writers_stopped(False)
        with patch("cutover_native_opendesign.subprocess.run") as run:
            run.return_value = SimpleNamespace(returncode=0)
            with self.assertRaisesRegex(NativeDataCutoverError, "Core must be stopped"):
                _require_writers_stopped(True)

    def test_cutover_uses_no_private_database_reader(self) -> None:
        paths = (
            SERVICE_ROOT / "native_data_cutover.py",
            SERVICE_ROOT / "native_cutover_state.py",
            SERVICE_ROOT / "official_public_inventory.py",
            SERVICE_ROOT / "official_inventory_process.py",
            SERVICE_ROOT / "official_inventory_values.py",
        )
        source = "\n".join(path.read_text(encoding="utf-8") for path in paths)
        self.assertNotIn("import sqlite3", source)
        self.assertNotIn("sqlite3.connect", source)
        self.assertNotIn("app.sqlite", source)


if __name__ == "__main__":
    unittest.main()
