"""Official-release selection, migration, rollback, and bridge degradation proofs."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import sys
import tempfile
import unittest


APP_ROOT = Path(__file__).resolve().parents[1]
SERVICE_ROOT = APP_ROOT / "service"
sys.path.insert(0, str(SERVICE_ROOT))

from native_official_update import OfficialUpdateError, perform_official_update  # noqa: E402
from official_opendesign_release import (  # noqa: E402
    OfficialReleaseError,
    load_official_release,
)
from official_release_selection import (  # noqa: E402
    ensure_release_selection,
    read_release_selection,
)


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


def _candidate_descriptor(path: Path) -> Path:
    payload = json.loads((SERVICE_ROOT / "opendesign_official_release.json").read_text())
    payload["version"] = "0.17.0"
    payload["source"]["tag"] = "open-design-v0.17.0"
    payload["oci"]["reference"] = "0.17.0"
    payload["oci"]["expected_version"] = "0.17.0"
    payload["oci"]["manifest"]["digest"] = "sha256:" + "f" * 64
    payload["oci"]["attestation"]["subject_manifest_digest"] = "sha256:" + "f" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _inventory(release, *, changed: bool) -> dict:
    digest = ("d" if changed else "c") * 64
    return {
        "schema_version": "1",
        "kind": "official-opendesign-public-inventory",
        "release": {
            "version": release.version,
            "manifest_digest": release.manifest_digest,
            "rootfs_snapshot_sha256": "e" * 64,
        },
        "categories": {name: {"count": 1, "sha256": digest} for name in CATEGORIES},
        "semantic_content_retained": False,
        "private_database_read": False,
    }


def _force_remove(path: Path) -> None:
    if not path.exists():
        return
    for item in sorted(path.rglob("*"), key=lambda value: len(value.parts), reverse=True):
        try:
            item.chmod(0o700 if item.is_dir() else 0o600)
        except OSError:
            pass
    try:
        path.chmod(0o700)
    except OSError:
        pass
    shutil.rmtree(path, ignore_errors=True)


class OfficialUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = Path(tempfile.mkdtemp(prefix="official-update-test-"))
        self.addCleanup(_force_remove, self.temporary)
        self.data_root = self.temporary / "data"
        self.native = self.data_root / "opendesign-native"
        self.artifacts = self.temporary / "artifacts"
        self.native.mkdir(parents=True)
        self.artifacts.mkdir()
        (self.native / "app.sqlite").write_bytes(b"private canonical data")
        (self.native / "project.txt").write_text("semantic design content", encoding="utf-8")
        self.current = load_official_release()
        ensure_release_selection(self.data_root, self.current)
        self.candidate_path = _candidate_descriptor(self.temporary / "candidate.json")
        self.candidate = load_official_release(self.candidate_path, require_bundled_pin=False)

    def _installation(self, release):
        return SimpleNamespace(
            path=self.artifacts / "official" / release.digest_key,
            rootfs=self.temporary / f"rootfs-{release.version}",
            release=release,
            rootfs_snapshot_sha256="e" * 64,
            installed_at="2026-08-28T00:00:00Z",
        )

    def _run(self, control, *, probe=None):
        def inventory(installation, *, data_dir: Path, log_path: Path):
            self.assertTrue((data_dir / "project.txt").is_file())
            log_path.write_text("supported public APIs only", encoding="utf-8")
            changed = installation.release.manifest_digest == self.candidate.manifest_digest
            if changed:
                (data_dir / "upstream-migration").write_text("0.17.0", encoding="utf-8")
            return _inventory(installation.release, changed=changed)

        def install(_destination, *, release):
            self.assertEqual(release.manifest_digest, self.candidate.manifest_digest)
            return self._installation(release)

        def verify(_path, *, expected_release):
            return self._installation(expected_release)

        return perform_official_update(
            self.data_root,
            self.artifacts,
            self.candidate_path,
            workspace_id="default",
            confirmed=True,
            update_id="update_unit_test",
            install_runner=install,
            verify_runner=verify,
            inventory_runner=inventory,
            delegation_probe=probe or (
                lambda _installation, *, data_dir, log_path: {
                    "state": "ready",
                    "contract": "public-opendesign-delegation-v1",
                    "evidence": "unit-test",
                }
            ),
            sidecar_control=control,
        )

    def test_user_selected_official_release_is_generic_but_origin_locked(self) -> None:
        self.assertEqual(self.candidate.version, "0.17.0")
        self.assertEqual(self.candidate.image, "ghcr.io/nexu-io/od")
        self.assertEqual(self.candidate.customizations, ())

        payload = json.loads(self.candidate_path.read_text())
        payload["source"]["repository"] = "https://example.invalid/fork.git"
        fork = self.temporary / "fork.json"
        fork.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(OfficialReleaseError, "not official"):
            load_official_release(fork, require_bundled_pin=False)

    def test_selection_digest_detects_workspace_tampering(self) -> None:
        selection = self.data_root / "official-release-selection.json"
        payload = json.loads(selection.read_text())
        payload["release"]["version"] = "9.9.9"
        selection.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(OfficialReleaseError, "digest"):
            read_release_selection(self.data_root)

    def test_update_runs_upstream_migration_and_keeps_native_when_bridges_degrade(self) -> None:
        calls: list[str] = []

        def control(operation: str, _workspace_id: str) -> dict:
            calls.append(operation)
            return {"ready": operation == "prewarm"}

        def incompatible_probe(_installation, *, data_dir: Path, log_path: Path):
            raise RuntimeError("candidate removed a delegation endpoint")

        result = self._run(control, probe=incompatible_probe)

        self.assertTrue(result["update_applied"])
        self.assertEqual(result["update"]["phase"], "committed")
        self.assertEqual(result["update"]["bridges"]["delegation"]["state"], "degraded")
        self.assertEqual(result["update"]["bridges"]["model_access"]["state"], "degraded")
        self.assertEqual(calls, ["stop", "prewarm"])
        self.assertEqual(read_release_selection(self.data_root).release.version, "0.17.0")
        self.assertEqual((self.native / "upstream-migration").read_text(), "0.17.0")
        self.assertEqual((self.native / "project.txt").read_text(), "semantic design content")
        backup = self.data_root / result["update"]["backup_directory"]
        self.assertEqual((backup / "native-data/project.txt").read_text(), "semantic design content")
        self.assertFalse(backup.stat().st_mode & 0o222)

    def test_failed_candidate_startup_restores_full_previous_selection_and_data(self) -> None:
        calls: list[str] = []
        prewarms = 0

        def control(operation: str, _workspace_id: str) -> dict:
            nonlocal prewarms
            calls.append(operation)
            if operation == "stop":
                return {"ready": False}
            prewarms += 1
            return {"ready": prewarms == 2}

        result = self._run(control)

        self.assertFalse(result["update_applied"])
        self.assertEqual(result["update"]["phase"], "rolled_back")
        self.assertTrue(result["update"]["native_ready"])
        self.assertEqual(calls, ["stop", "prewarm", "stop", "prewarm"])
        self.assertEqual(read_release_selection(self.data_root).release.version, "0.16.1")
        self.assertFalse((self.native / "upstream-migration").exists())
        self.assertEqual((self.native / "project.txt").read_text(), "semantic design content")

    def test_failed_previous_startup_stays_quiesced_for_operator_recovery(self) -> None:
        calls: list[str] = []

        def control(operation: str, _workspace_id: str) -> dict:
            calls.append(operation)
            return {"ready": False}

        with self.assertRaisesRegex(OfficialUpdateError, "operator intervention"):
            self._run(control)

        self.assertEqual(calls, ["stop", "prewarm", "stop", "prewarm"])
        marker = json.loads((self.data_root / "official-update.json").read_text())
        self.assertEqual(marker["phase"], "recovery_required")
        self.assertFalse(marker["native_ready"])
        self.assertFalse(marker["rolled_back"])
        self.assertTrue((self.data_root / "native-cutover-quiesce.json").is_file())
        self.assertEqual(read_release_selection(self.data_root).release.version, "0.16.1")
        self.assertFalse((self.native / "upstream-migration").exists())
        self.assertEqual((self.native / "project.txt").read_text(), "semantic design content")


if __name__ == "__main__":
    unittest.main()
