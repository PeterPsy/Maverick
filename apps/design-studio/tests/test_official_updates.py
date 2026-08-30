"""Official-release selection, migration, rollback, and bridge degradation proofs."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
import sys
import tempfile
import unittest


APP_ROOT = Path(__file__).resolve().parents[1]
SERVICE_ROOT = APP_ROOT / "service"
sys.path.insert(0, str(SERVICE_ROOT))

from native_official_update import (  # noqa: E402
    OfficialUpdateError,
    _live_bridge_results,
    perform_official_update,
    recover_interrupted_official_update,
)
from official_update_lock import official_update_lock  # noqa: E402
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


def _inventory(
    release,
    *,
    changed: bool,
    removed: tuple[str, ...] = (),
    content_changed: bool = False,
) -> dict:
    digest = ("d" if changed else "c") * 64
    categories = {
        name: {
            "count": 0 if name in removed else 1,
            "sha256": digest,
        }
        for name in CATEGORIES
    }
    identity_sets = {
        name: (
            []
            if name in removed
            else [sha256(f"{name}:native-identity".encode("utf-8")).hexdigest()]
        )
        for name in CATEGORIES
    }
    content_sets = {
        name: (
            []
            if name in removed
            else [
                sha256(
                    f"{name}:native-content:{'changed' if content_changed else 'preserved'}".encode(
                        "utf-8"
                    )
                ).hexdigest()
            ]
        )
        for name in CATEGORIES
    }
    return {
        "schema_version": "1",
        "kind": "official-opendesign-public-inventory",
        "release": {
            "version": release.version,
            "manifest_digest": release.manifest_digest,
            "rootfs_snapshot_sha256": "e" * 64,
        },
        "categories": categories,
        "identity_sets": identity_sets,
        "content_sets": content_sets,
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

    def _run(
        self,
        control,
        *,
        probe=None,
        removed: tuple[str, ...] = (),
        content_changed: bool = False,
    ):
        def inventory(installation, *, data_dir: Path, log_path: Path):
            self.assertTrue((data_dir / "project.txt").is_file())
            log_path.write_text("supported public APIs only", encoding="utf-8")
            changed = installation.release.manifest_digest == self.candidate.manifest_digest
            if changed:
                (data_dir / "upstream-migration").write_text("0.17.0", encoding="utf-8")
            return _inventory(
                installation.release,
                changed=changed,
                removed=removed if changed else (),
                content_changed=content_changed if changed else False,
            )

        def install(_destination, *, release):
            self.assertEqual(release.manifest_digest, self.candidate.manifest_digest)
            return self._installation(release)

        def verify(_path, *, expected_release):
            return self._installation(expected_release)

        def verified_control(operation: str, workspace_id: str) -> dict:
            response = control(operation, workspace_id)
            if (
                operation == "stop"
                and isinstance(response, dict)
                and response.get("ready") is False
                and "data_root" not in response
            ):
                return {
                    "workspace_id": workspace_id,
                    "app_id": "design-studio",
                    "data_root": str(self.data_root.resolve()),
                    "ready": False,
                    "browser_sessions_revoked": True,
                    "declared_service_count": 1,
                    "stopped_service_count": 1,
                    "verified_stopped_service_count": 1,
                    "services": [
                        {
                            "sidecar_id": "opendesign",
                            "previous_instance_id": "unit-test-instance",
                            "live_instance_id": None,
                            "state": "stopped",
                        }
                    ],
                }
            if operation == "prewarm" and isinstance(response, dict):
                ready = response.get("ready") is True
                if "data_root" not in response:
                    return {
                        "workspace_id": workspace_id,
                        "app_id": "design-studio",
                        "data_root": str(self.data_root.resolve()),
                        "ready": ready,
                        "declared_service_count": 1,
                        "verified_ready_service_count": 1 if ready else 0,
                        "services": [
                            {
                                "sidecar_id": "opendesign",
                                "live_instance_id": (
                                    "unit-test-ready-instance" if ready else None
                                ),
                                "state": "ready" if ready else "failed",
                            }
                        ],
                    }
            if operation == "status" and isinstance(response, dict):
                services = response.get("services")
                if isinstance(services, list) and "data_root" not in response:
                    normalized = []
                    for service in services:
                        item = dict(service)
                        item.setdefault("sidecar_id", "opendesign")
                        item.setdefault(
                            "live_instance_id",
                            None if item.get("state") in {"stopped", "not_started", "failed"} else "live",
                        )
                        normalized.append(item)
                    verified = sum(
                        item.get("live_instance_id") is None
                        and item.get("state") in {"stopped", "not_started", "failed"}
                        for item in normalized
                    )
                    return {
                        "workspace_id": workspace_id,
                        "app_id": "design-studio",
                        "data_root": str(self.data_root.resolve()),
                        "declared_service_count": len(normalized),
                        "verified_stopped_service_count": verified,
                        "services": normalized,
                    }
            return response

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
            sidecar_control=verified_control,
        )

    def _verified_control(self, operation: str, workspace_id: str) -> dict:
        if operation == "stop":
            return {
                "workspace_id": workspace_id,
                "app_id": "design-studio",
                "data_root": str(self.data_root.resolve()),
                "ready": False,
                "browser_sessions_revoked": True,
                "declared_service_count": 1,
                "stopped_service_count": 1,
                "verified_stopped_service_count": 1,
                "services": [
                    {
                        "sidecar_id": "opendesign",
                        "previous_instance_id": "unit-test-instance",
                        "live_instance_id": None,
                        "state": "stopped",
                    }
                ],
            }
        if operation == "prewarm":
            return {
                "workspace_id": workspace_id,
                "app_id": "design-studio",
                "data_root": str(self.data_root.resolve()),
                "ready": True,
                "declared_service_count": 1,
                "verified_ready_service_count": 1,
                "services": [
                    {
                        "sidecar_id": "opendesign",
                        "live_instance_id": "unit-test-ready-instance",
                        "state": "ready",
                    }
                ],
            }
        if operation == "release_quarantine":
            return {"ready": False, "quarantined": False, "released": True}
        raise AssertionError(operation)

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

    def test_post_update_handshake_uses_live_host_model_status_not_prepare_placeholder(self) -> None:
        (self.data_root / "bridge-capabilities.json").write_text(
            json.dumps(
                {
                    "schema_version": "1",
                    "manifest_digest": self.candidate.manifest_digest,
                    "model_access": {"state": "ready", "source": "placeholder"},
                    "delegation": {"state": "ready"},
                }
            ),
            encoding="utf-8",
        )
        (self.data_root / "native-host-status.json").write_text(
            json.dumps(
                {
                    "schema_version": "1",
                    "mode": "official-native",
                    "state": "ready",
                    "manifest_digest": self.candidate.manifest_digest,
                    "model_bridge": {
                        "state": "degraded",
                        "reason": "core_broker_unavailable",
                        "semantic_enrichment": False,
                    },
                }
            ),
            encoding="utf-8",
        )

        result = _live_bridge_results(
            self.data_root,
            {"state": "ready"},
            manifest_digest=self.candidate.manifest_digest,
        )

        self.assertEqual(
            result["model_access"],
            {
                "state": "degraded",
                "reason": "core_broker_unavailable",
                "semantic_enrichment": False,
            },
        )

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
        self.assertEqual(result["update"]["migration_guard"]["state"], "passed")
        self.assertEqual(calls, ["stop", "prewarm"])
        self.assertEqual(read_release_selection(self.data_root).release.version, "0.17.0")
        self.assertEqual((self.native / "upstream-migration").read_text(), "0.17.0")
        self.assertEqual((self.native / "project.txt").read_text(), "semantic design content")
        backup = self.data_root / result["update"]["backup_directory"]
        self.assertEqual((backup / "native-data/project.txt").read_text(), "semantic design content")
        self.assertFalse(backup.stat().st_mode & 0o222)

    def test_failed_candidate_startup_never_rolls_back_a_durable_commit(self) -> None:
        calls: list[str] = []
        prewarms = 0

        def control(operation: str, _workspace_id: str) -> dict:
            nonlocal prewarms
            calls.append(operation)
            if operation == "stop":
                return {"ready": False}
            prewarms += 1
            return {"ready": False}

        result = self._run(control)

        self.assertTrue(result["update_applied"])
        self.assertEqual(result["error"], "candidate_startup_failed")
        self.assertEqual(result["update"]["phase"], "committed")
        self.assertFalse(result["update"]["native_ready"])
        self.assertEqual(calls, ["stop", "prewarm"])
        self.assertEqual(read_release_selection(self.data_root).release.version, "0.17.0")
        self.assertTrue((self.native / "upstream-migration").exists())
        self.assertEqual((self.native / "project.txt").read_text(), "semantic design content")

    def test_preparing_marker_is_durable_before_quiescence_and_startup_recovers_it(self) -> None:
        from unittest.mock import patch

        with patch(
            "native_official_update.quiesce_native_host",
            side_effect=SystemExit("simulated death before quiescence"),
        ):
            with self.assertRaisesRegex(SystemExit, "before quiescence"):
                self._run(self._verified_control)

        marker = json.loads((self.data_root / "official-update.json").read_text())
        self.assertEqual(marker["phase"], "preparing")
        self.assertFalse((self.data_root / "native-cutover-quiesce.json").exists())

        environment = dict(__import__("os").environ)
        environment["PYTHONPATH"] = str(APP_ROOT.parents[1])
        prepared = subprocess.run(
            [sys.executable, str(APP_ROOT / "hooks" / "sidecar_prepare.py")],
            input=json.dumps(
                {
                    "app_id": "design-studio",
                    "workspace_id": "default",
                    "data_root": str(self.data_root),
                    "sidecar_id": "opendesign",
                    "managed_writer_stopped": True,
                }
            ),
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )

        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        recovered = json.loads((self.data_root / "official-update.json").read_text())
        self.assertEqual(recovered["phase"], "rolled_back")
        self.assertFalse(recovered["native_ready"])
        self.assertFalse((self.data_root / "native-cutover-quiesce.json").exists())

    def test_crash_during_backup_build_ignores_partial_backup_on_startup_recovery(self) -> None:
        from unittest.mock import patch

        real_copy = __import__("native_official_update").copy_verified_tree

        def crash_during_backup(source: Path, destination: Path):
            if destination.name == "native-data" and destination.parent.name.endswith(
                ".backup"
            ):
                destination.mkdir(parents=True)
                (destination / "partial.txt").write_text("incomplete", encoding="utf-8")
                raise SystemExit("simulated death during backup")
            return real_copy(source, destination)

        with patch(
            "native_official_update.copy_verified_tree",
            side_effect=crash_during_backup,
        ):
            with self.assertRaisesRegex(SystemExit, "during backup"):
                self._run(self._verified_control)

        staging = self.data_root / ".update_unit_test.backup"
        final_backup = (
            self.data_root
            / "opendesign-update-backups/official-update-update_unit_test"
        )
        self.assertTrue(staging.is_dir())
        self.assertFalse(final_backup.exists())

        environment = dict(__import__("os").environ)
        environment["PYTHONPATH"] = str(APP_ROOT.parents[1])
        prepared = subprocess.run(
            [sys.executable, str(APP_ROOT / "hooks" / "sidecar_prepare.py")],
            input=json.dumps(
                {
                    "app_id": "design-studio",
                    "workspace_id": "default",
                    "data_root": str(self.data_root),
                    "sidecar_id": "opendesign",
                    "managed_writer_stopped": True,
                }
            ),
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )

        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        recovered = json.loads((self.data_root / "official-update.json").read_text())
        self.assertEqual(recovered["phase"], "rolled_back")
        self.assertFalse(recovered["native_ready"])
        self.assertFalse(staging.exists())
        self.assertEqual(
            (self.native / "project.txt").read_text(encoding="utf-8"),
            "semantic design content",
        )

    def test_candidate_is_committed_before_prewarm_can_expose_it(self) -> None:
        observed_phase = ""

        def control(operation: str, _workspace_id: str) -> dict:
            nonlocal observed_phase
            if operation == "stop":
                return {"ready": False}
            observed_phase = json.loads(
                (self.data_root / "official-update.json").read_text(encoding="utf-8")
            )["phase"]
            (self.native / "post-prewarm-write.txt").write_text(
                "must-survive",
                encoding="utf-8",
            )
            return {"ready": True}

        result = self._run(control)

        self.assertEqual(observed_phase, "committed")
        self.assertTrue(result["update_applied"])
        self.assertEqual(
            (self.native / "post-prewarm-write.txt").read_text(encoding="utf-8"),
            "must-survive",
        )

    def test_host_prepare_never_claims_post_spawn_readiness(self) -> None:
        def unavailable(operation: str, _workspace_id: str) -> dict:
            return {"ready": False}

        result = self._run(unavailable)
        self.assertEqual(result["update"]["phase"], "committed")
        self.assertFalse(result["update"]["native_ready"])

        environment = dict(__import__("os").environ)
        environment["PYTHONPATH"] = str(APP_ROOT.parents[1])
        prepared = subprocess.run(
            [sys.executable, str(APP_ROOT / "hooks" / "sidecar_prepare.py")],
            input=json.dumps(
                {
                    "app_id": "design-studio",
                    "workspace_id": "default",
                    "data_root": str(self.data_root),
                    "sidecar_id": "opendesign",
                    "managed_writer_stopped": True,
                }
            ),
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        after_prepare = json.loads(
            (self.data_root / "official-update.json").read_text(encoding="utf-8")
        )
        self.assertFalse(after_prepare["native_ready"])
        backup = self.data_root / result["update"]["backup_directory"]
        self.assertFalse(backup.stat().st_mode & 0o222)

        (self.data_root / "native-host-status.json").write_text(
            json.dumps(
                {
                    "schema_version": "1",
                    "mode": "official-native",
                    "state": "ready",
                    "manifest_digest": self.candidate.manifest_digest,
                    "model_bridge": {
                        "state": "ready",
                        "semantic_enrichment": False,
                    },
                }
            ),
            encoding="utf-8",
        )
        calls: list[str] = []

        def verified(operation: str, workspace_id: str) -> dict:
            calls.append(operation)
            return self._verified_control(operation, workspace_id)

        recovered = recover_interrupted_official_update(
            self.data_root,
            workspace_id="default",
            sidecar_control=verified,
        )

        self.assertEqual(calls, ["prewarm"])
        self.assertTrue(recovered["recovered"])
        self.assertTrue(recovered["update"]["native_ready"])

    def test_crash_after_prewarm_preserves_candidate_writes_during_recovery(self) -> None:
        def control(operation: str, _workspace_id: str) -> dict:
            if operation == "stop":
                return {"ready": False}
            marker = json.loads(
                (self.data_root / "official-update.json").read_text(encoding="utf-8")
            )
            self.assertEqual(marker["phase"], "committed")
            (self.native / "write-after-prewarm.txt").write_text(
                "canonical-after-commit",
                encoding="utf-8",
            )
            raise SystemExit("simulated death after prewarm")

        with self.assertRaisesRegex(SystemExit, "after prewarm"):
            self._run(control)

        recovered = recover_interrupted_official_update(
            self.data_root,
            workspace_id="default",
            sidecar_control=self._verified_control,
        )

        self.assertEqual(recovered["update"]["phase"], "committed")
        self.assertTrue(recovered["update"]["native_ready"])
        self.assertEqual(read_release_selection(self.data_root).release.version, "0.17.0")
        self.assertEqual(
            (self.native / "write-after-prewarm.txt").read_text(encoding="utf-8"),
            "canonical-after-commit",
        )

    def test_crash_after_native_retirement_is_recovered_from_durable_journal(self) -> None:
        from unittest.mock import patch

        real_replace = __import__("os").replace

        def crash_after_replace(source, destination):
            real_replace(source, destination)
            if Path(source) == self.native:
                raise SystemExit("simulated process death after native retirement")

        with patch("native_official_update.os.replace", side_effect=crash_after_replace):
            with self.assertRaisesRegex(SystemExit, "simulated process death"):
                self._run(self._verified_control)

        self.assertFalse(self.native.exists())
        journal = json.loads(
            (self.data_root / "official-update-cutover-journal.json").read_text()
        )
        self.assertEqual(journal["step"], "retire_native_intent")
        self.assertEqual(
            json.loads((self.data_root / "official-update.json").read_text())["phase"],
            "activating",
        )
        # Legacy prepared backups predate the optional delegation evidence.
        # Recovery must still restore canonical data and degrade only that bridge.
        (
            self.data_root
            / "opendesign-update-backups/official-update-update_unit_test"
            / "previous-delegation.json"
        ).unlink()

        environment = dict(__import__("os").environ)
        environment["PYTHONPATH"] = str(APP_ROOT.parents[1])
        prepared = subprocess.run(
            [sys.executable, str(APP_ROOT / "hooks" / "sidecar_prepare.py")],
            input=json.dumps(
                {
                    "app_id": "design-studio",
                    "workspace_id": "default",
                    "data_root": str(self.data_root),
                    "sidecar_id": "opendesign",
                    "managed_writer_stopped": True,
                }
            ),
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        projection = json.loads(prepared.stdout)
        launch = json.loads(
            projection["environment"][
                "MAVERICK_APP_OPENDESIGN_LAUNCH_CONFIGURATION"
            ]
        )
        self.assertEqual(launch["release"]["version"], "0.16.1")

        recovered = json.loads((self.data_root / "official-update.json").read_text())
        self.assertEqual(recovered["phase"], "rolled_back")
        self.assertFalse(recovered["native_ready"])
        self.assertEqual((self.native / "project.txt").read_text(), "semantic design content")
        self.assertFalse((self.native / "upstream-migration").exists())
        self.assertFalse((self.data_root / "official-update-cutover-journal.json").exists())
        self.assertFalse((self.data_root / "native-cutover-quiesce.json").exists())

        explicit = recover_interrupted_official_update(
            self.data_root,
            workspace_id="default",
            sidecar_control=self._verified_control,
        )
        self.assertTrue(explicit["recovered"])
        self.assertEqual(explicit["update"]["phase"], "rolled_back")
        self.assertTrue(explicit["update"]["native_ready"])

    def test_update_lock_rejects_a_concurrent_transaction(self) -> None:
        with official_update_lock(self.data_root) as acquired:
            self.assertTrue(acquired)
            with self.assertRaisesRegex(OfficialUpdateError, "transaction is active"):
                self._run(self._verified_control)

    def test_destructive_candidate_migration_is_rejected_before_activation(self) -> None:
        calls: list[str] = []

        def control(operation: str, _workspace_id: str) -> dict:
            calls.append(operation)
            return {"ready": operation == "prewarm"}

        with self.assertRaisesRegex(OfficialUpdateError, "removed protected native identities"):
            self._run(control, removed=("projects", "conversations", "project_files"))

        self.assertEqual(calls, ["stop", "prewarm"])
        self.assertEqual(read_release_selection(self.data_root).release.version, "0.16.1")
        self.assertFalse((self.native / "upstream-migration").exists())
        self.assertEqual((self.native / "project.txt").read_text(), "semantic design content")

    def test_same_id_content_mutation_is_rejected_before_activation(self) -> None:
        calls: list[str] = []

        def control(operation: str, _workspace_id: str) -> dict:
            calls.append(operation)
            return {"ready": operation == "prewarm"}

        with self.assertRaisesRegex(OfficialUpdateError, "changed protected native content"):
            self._run(control, content_changed=True)

        self.assertEqual(calls, ["stop", "prewarm"])
        self.assertEqual(read_release_selection(self.data_root).release.version, "0.16.1")
        self.assertFalse((self.native / "upstream-migration").exists())

    def test_pre_activation_recovery_failure_is_marked_and_stays_quiesced(self) -> None:
        calls: list[str] = []

        def control(operation: str, _workspace_id: str) -> dict:
            calls.append(operation)
            return {"ready": False}

        with self.assertRaisesRegex(OfficialUpdateError, "operator intervention"):
            self._run(control, removed=("projects",))

        self.assertEqual(calls, ["stop", "prewarm", "stop"])
        marker = json.loads((self.data_root / "official-update.json").read_text())
        self.assertEqual(marker["phase"], "recovery_required")
        self.assertEqual(marker["migration_guard"]["state"], "failed")
        self.assertFalse(marker["native_ready"])
        self.assertTrue((self.data_root / "native-cutover-quiesce.json").is_file())
        self.assertEqual(read_release_selection(self.data_root).release.version, "0.16.1")

    def test_failed_committed_startup_stays_quiesced_without_rolling_back(self) -> None:
        calls: list[str] = []

        def control(operation: str, _workspace_id: str) -> dict:
            calls.append(operation)
            return {"ready": False}

        result = self._run(control)
        self.assertTrue(result["update_applied"])
        self.assertEqual(result["update"]["phase"], "committed")

        with self.assertRaisesRegex(OfficialUpdateError, "operator intervention"):
            recover_interrupted_official_update(
                self.data_root,
                workspace_id="default",
                sidecar_control=control,
            )

        self.assertEqual(calls, ["stop", "prewarm", "prewarm"])
        marker = json.loads((self.data_root / "official-update.json").read_text())
        self.assertEqual(marker["phase"], "committed")
        self.assertFalse(marker["native_ready"])
        self.assertFalse(marker["rolled_back"])
        self.assertTrue((self.data_root / "native-cutover-quiesce.json").is_file())
        self.assertEqual(read_release_selection(self.data_root).release.version, "0.17.0")
        self.assertTrue((self.native / "upstream-migration").exists())
        self.assertEqual((self.native / "project.txt").read_text(), "semantic design content")

    def test_committed_recovery_exception_restores_quiescence_without_rollback(self) -> None:
        calls: list[str] = []
        prewarms = 0

        def control(operation: str, _workspace_id: str) -> dict:
            nonlocal prewarms
            calls.append(operation)
            if operation == "stop":
                return {"ready": False}
            prewarms += 1
            if prewarms == 1:
                return {"ready": False}
            raise RuntimeError("sidecar control channel failed")

        result = self._run(control)
        self.assertTrue(result["update_applied"])
        with self.assertRaisesRegex(OfficialUpdateError, "operator intervention"):
            recover_interrupted_official_update(
                self.data_root,
                workspace_id="default",
                sidecar_control=control,
            )

        marker = json.loads((self.data_root / "official-update.json").read_text())
        self.assertEqual(marker["phase"], "committed")
        self.assertFalse(marker["native_ready"])
        self.assertTrue((self.data_root / "native-cutover-quiesce.json").is_file())
        self.assertEqual(calls, ["stop", "prewarm", "prewarm"])

    def test_recovery_retries_failed_stops_and_marks_only_after_writer_is_stopped(self) -> None:
        from unittest.mock import patch

        calls: list[str] = []
        stop_calls = 0

        real_replace = __import__("os").replace

        def crash_after_replace(source, destination):
            real_replace(source, destination)
            if Path(source) == self.native:
                raise SystemExit("simulated interrupted activation")

        with patch("native_official_update.os.replace", side_effect=crash_after_replace):
            with self.assertRaisesRegex(SystemExit, "interrupted activation"):
                self._run(self._verified_control)

        def control(operation: str, _workspace_id: str) -> dict:
            nonlocal stop_calls
            calls.append(operation)
            if operation == "stop":
                stop_calls += 1
                raise RuntimeError("stop response lost")
            if operation == "status":
                return {
                    "workspace_id": "default",
                    "app_id": "design-studio",
                    "data_root": str(self.data_root.resolve()),
                    "declared_service_count": 1,
                    "verified_stopped_service_count": 1,
                    "services": [
                        {
                            "sidecar_id": "opendesign",
                            "live_instance_id": None,
                            "state": "stopped",
                        }
                    ],
                }
            return self._verified_control(operation, "default")

        recovered = recover_interrupted_official_update(
            self.data_root,
            workspace_id="default",
            sidecar_control=control,
        )

        self.assertEqual(recovered["update"]["phase"], "rolled_back")
        self.assertTrue(recovered["update"]["native_ready"])
        self.assertEqual(stop_calls, 3)
        self.assertIn("status", calls)
        self.assertFalse((self.data_root / "native-cutover-quiesce.json").exists())

    def test_unconfirmed_writer_is_durably_quarantined_before_recovery_marker(self) -> None:
        stop_calls = 0
        quarantine_calls = 0
        writer_active = True
        quarantined = False

        def control(operation: str, _workspace_id: str) -> dict:
            nonlocal stop_calls, quarantine_calls, writer_active, quarantined
            if operation == "stop":
                stop_calls += 1
                raise RuntimeError("Core could not stop the active writer")
            if operation == "status":
                return {"services": [{"state": "ready"}]}
            if operation == "quarantine":
                quarantine_calls += 1
                quarantined = True
                if quarantine_calls == 1:
                    raise RuntimeError("quarantine completed but its response was lost")
                return {
                    "quarantined": True,
                    "persistent": True,
                    "proxy_revoked": True,
                    "browser_sessions_revoked": True,
                    "model_access_revoked": True,
                    "writer_stop_confirmed": False,
                }
            raise AssertionError(operation)

        with self.assertRaisesRegex(OfficialUpdateError, "operator intervention"):
            self._run(control)

        marker = json.loads((self.data_root / "official-update.json").read_text())
        self.assertEqual(marker["phase"], "recovery_required")
        self.assertEqual(
            marker["bridges"]["model_access"],
            {"state": "disabled", "reason": "core_sidecar_quarantine"},
        )
        self.assertTrue(quarantined)
        self.assertEqual(quarantine_calls, 2)
        self.assertTrue(writer_active)
        self.assertEqual(stop_calls, 9)
        self.assertTrue((self.data_root / "native-cutover-quiesce.json").is_file())


if __name__ == "__main__":
    unittest.main()
