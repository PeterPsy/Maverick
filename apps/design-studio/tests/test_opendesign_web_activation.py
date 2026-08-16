from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
SERVICE_ROOT = ROOT / "apps/design-studio/service"
RUNTIME = "a" * 64
WEB_A = "b" * 64
WEB_B = "c" * 64
VERIFIED_ARTIFACTS = {RUNTIME: "0.16.1"}
VERIFIED_OVERLAYS = {
    digest: {
        "od_version": "0.16.1",
        "compatible_runtime_artifact_sha256": [RUNTIME],
    }
    for digest in (WEB_A, WEB_B)
}


def _load(name: str, filename: str):
    sys.path.insert(0, str(SERVICE_ROOT))
    spec = importlib.util.spec_from_file_location(name, SERVICE_ROOT / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class WebActivationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.model = _load("opendesign_generation_model", "opendesign_generation_model.py")
        self.control = _load("opendesign_generation_control", "opendesign_generation_control.py")
        self.activation = _load("opendesign_web_activation", "opendesign_web_activation.py")
        self.temp = tempfile.TemporaryDirectory(prefix="maverick-web-activation-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "opendesign"
        for child in ("instances/gen_current/data", "backups", "migrations", "web-activations"):
            (self.root / child).mkdir(parents=True, exist_ok=True)
        self.data_file = self.root / "instances/gen_current/data/design.db"
        self.data_file.write_bytes(b"immutable active data bytes")
        self.source = self.model.LaunchSelection(RUNTIME, WEB_A, "0.16.1", "gen_current")
        initial = self.model.GenerationControl(
            active=self.source,
            previous_release=None,
            previous_web=None,
            migration_id=None,
            web_activation_id=None,
            updated_at="2026-08-12T10:00:00Z",
        )
        self.control.write_generation_control(
            self.root,
            initial,
            verified_artifacts=VERIFIED_ARTIFACTS,
            verified_overlays=VERIFIED_OVERLAYS,
        )

    def test_web_only_cutover_changes_only_overlay_and_records_readiness(self) -> None:
        before_stat = self.data_file.stat()
        calls = 0

        def restart():
            nonlocal calls
            calls += 1
            return {"ready": True, "service_count": 1, "ignored": "/private/path"}

        outcome = self.activation.activate_web_overlay(
            self.root,
            target_web_overlay_sha256=WEB_B,
            web_activation_id="web_cutover_001",
            verified_artifacts=VERIFIED_ARTIFACTS,
            verified_overlays=VERIFIED_OVERLAYS,
            restart_sidecars=restart,
            now=lambda: "2026-08-12T10:00:01Z",
        )

        self.assertTrue(outcome.activated)
        self.assertFalse(outcome.rolled_back)
        self.assertEqual(calls, 1)
        self.assertEqual(outcome.control.active.web_overlay_sha256, WEB_B)
        self.assertTrue(outcome.control.active.same_runtime_and_data(self.source))
        self.assertEqual(outcome.control.previous_web, self.source)
        self.assertIsNone(outcome.control.previous_release)
        self.assertIsNone(outcome.control.migration_id)
        self.assertEqual(self.data_file.read_bytes(), b"immutable active data bytes")
        self.assertEqual(self.data_file.stat().st_ino, before_stat.st_ino)
        journal = self.control.load_web_activation_journal(
            self.root,
            "web_cutover_001",
            verified_artifacts=VERIFIED_ARTIFACTS,
            verified_overlays=VERIFIED_OVERLAYS,
        )
        self.assertEqual(journal.state, "ready_committed")
        self.assertEqual(journal.readiness["service_count"], 1)
        self.assertNotIn("ignored", journal.readiness)

    def test_failed_candidate_readiness_restores_previous_overlay_without_data_change(self) -> None:
        outcomes = iter(
            (
                {"ready": False, "service_count": 1, "detail": "/secret"},
                {"ready": True, "service_count": 1},
            )
        )

        outcome = self.activation.activate_web_overlay(
            self.root,
            target_web_overlay_sha256=WEB_B,
            web_activation_id="web_rollback_001",
            verified_artifacts=VERIFIED_ARTIFACTS,
            verified_overlays=VERIFIED_OVERLAYS,
            restart_sidecars=lambda: next(outcomes),
            now=lambda: "2026-08-12T10:00:02Z",
        )

        self.assertFalse(outcome.activated)
        self.assertTrue(outcome.rolled_back)
        self.assertEqual(outcome.control.active, self.source)
        self.assertEqual(outcome.control.previous_web.web_overlay_sha256, WEB_B)
        self.assertEqual(self.data_file.read_bytes(), b"immutable active data bytes")
        journal = self.control.load_web_activation_journal(
            self.root,
            "web_rollback_001",
            verified_artifacts=VERIFIED_ARTIFACTS,
            verified_overlays=VERIFIED_OVERLAYS,
        )
        self.assertEqual(journal.state, "rolled_back")
        self.assertEqual(journal.error, "candidate_restart_failed:WebActivationError")
        self.assertNotIn("secret", str(journal.to_dict()))

    def test_recovery_finishes_readiness_after_cutover_crash(self) -> None:
        target = self.model.LaunchSelection(RUNTIME, WEB_B, "0.16.1", "gen_current")
        journal = self.model.WebActivationJournal(
            web_activation_id="web_recover_001",
            state="prepared",
            source=self.source,
            target=target,
            readiness={},
            error=None,
            created_at="2026-08-12T10:00:03Z",
            updated_at="2026-08-12T10:00:03Z",
        )
        self.control.write_web_activation_journal(
            self.root,
            journal,
            verified_artifacts=VERIFIED_ARTIFACTS,
            verified_overlays=VERIFIED_OVERLAYS,
        )
        cutover = self.model.GenerationControl(
            active=target,
            previous_release=None,
            previous_web=self.source,
            migration_id=None,
            web_activation_id="web_recover_001",
            updated_at="2026-08-12T10:00:03Z",
        )
        self.control.write_generation_control(
            self.root,
            cutover,
            verified_artifacts=VERIFIED_ARTIFACTS,
            verified_overlays=VERIFIED_OVERLAYS,
        )

        recovered = self.activation.recover_web_activation(
            self.root,
            verified_artifacts=VERIFIED_ARTIFACTS,
            verified_overlays=VERIFIED_OVERLAYS,
            restart_sidecars=lambda: {"ready": True, "service_count": 1},
            now=lambda: "2026-08-12T10:00:04Z",
        )

        self.assertIsNotNone(recovered)
        self.assertTrue(recovered.activated)
        committed = self.control.load_web_activation_journal(
            self.root,
            "web_recover_001",
            verified_artifacts=VERIFIED_ARTIFACTS,
            verified_overlays=VERIFIED_OVERLAYS,
        )
        self.assertEqual(committed.state, "ready_committed")

    def test_double_restart_failure_remains_recoverable_until_rollback_is_ready(self) -> None:
        attempts = iter(
            (
                {"ready": False, "service_count": 1},
                {"ready": False, "service_count": 1},
            )
        )
        with self.assertRaisesRegex(self.activation.WebActivationError, "rollback_restart_failed"):
            self.activation.activate_web_overlay(
                self.root,
                target_web_overlay_sha256=WEB_B,
                web_activation_id="web_rollback_pending_001",
                verified_artifacts=VERIFIED_ARTIFACTS,
                verified_overlays=VERIFIED_OVERLAYS,
                restart_sidecars=lambda: next(attempts),
                now=lambda: "2026-08-12T10:00:05Z",
            )

        pending = self.control.load_web_activation_journal(
            self.root,
            "web_rollback_pending_001",
            verified_artifacts=VERIFIED_ARTIFACTS,
            verified_overlays=VERIFIED_OVERLAYS,
        )
        self.assertEqual(pending.state, "rollback_restart_pending")
        self.assertEqual(
            self.model.reconcile_web_activation(
                self.control.load_generation_control(
                    self.root,
                    verified_artifacts=VERIFIED_ARTIFACTS,
                    verified_overlays=VERIFIED_OVERLAYS,
                ),
                pending,
            ),
            "rollback_restart_pending",
        )

        recovered = self.activation.recover_web_activation(
            self.root,
            verified_artifacts=VERIFIED_ARTIFACTS,
            verified_overlays=VERIFIED_OVERLAYS,
            restart_sidecars=lambda: {"ready": True, "service_count": 1},
            now=lambda: "2026-08-12T10:00:06Z",
        )

        self.assertIsNotNone(recovered)
        self.assertTrue(recovered.rolled_back)
        terminal = self.control.load_web_activation_journal(
            self.root,
            "web_rollback_pending_001",
            verified_artifacts=VERIFIED_ARTIFACTS,
            verified_overlays=VERIFIED_OVERLAYS,
        )
        self.assertEqual(terminal.state, "rolled_back")

    def test_new_activation_completes_pending_rollback_recovery_before_cutover(self) -> None:
        failed_restarts = iter(
            (
                {"ready": False, "service_count": 1},
                {"ready": False, "service_count": 1},
            )
        )
        with self.assertRaises(self.activation.WebActivationError):
            self.activation.activate_web_overlay(
                self.root,
                target_web_overlay_sha256=WEB_B,
                web_activation_id="web_old_pending_001",
                verified_artifacts=VERIFIED_ARTIFACTS,
                verified_overlays=VERIFIED_OVERLAYS,
                restart_sidecars=lambda: next(failed_restarts),
            )

        restart_calls = 0

        def ready_restart():
            nonlocal restart_calls
            restart_calls += 1
            return {"ready": True, "service_count": 1}

        outcome = self.activation.activate_web_overlay(
            self.root,
            target_web_overlay_sha256=WEB_B,
            web_activation_id="web_new_cutover_001",
            verified_artifacts=VERIFIED_ARTIFACTS,
            verified_overlays=VERIFIED_OVERLAYS,
            restart_sidecars=ready_restart,
        )

        self.assertEqual(restart_calls, 2)
        self.assertTrue(outcome.activated)
        old_journal = self.control.load_web_activation_journal(
            self.root,
            "web_old_pending_001",
            verified_artifacts=VERIFIED_ARTIFACTS,
            verified_overlays=VERIFIED_OVERLAYS,
        )
        self.assertEqual(old_journal.state, "rolled_back")
        control = self.control.load_generation_control(
            self.root,
            verified_artifacts=VERIFIED_ARTIFACTS,
            verified_overlays=VERIFIED_OVERLAYS,
        )
        self.assertEqual(control.web_activation_id, "web_new_cutover_001")

    def test_backend_restart_keeps_rollback_pending_until_verified_sidecar_readiness(self) -> None:
        failed_restarts = iter(
            (
                {"ready": False, "service_count": 1},
                {"ready": False, "service_count": 1},
            )
        )
        with self.assertRaises(self.activation.WebActivationError):
            self.activation.activate_web_overlay(
                self.root,
                target_web_overlay_sha256=WEB_B,
                web_activation_id="web_host_restart_pending_001",
                verified_artifacts=VERIFIED_ARTIFACTS,
                verified_overlays=VERIFIED_OVERLAYS,
                restart_sidecars=lambda: next(failed_restarts),
            )

        state = self.activation.web_activation_recovery_state(
            self.root,
            verified_artifacts=VERIFIED_ARTIFACTS,
            verified_overlays=VERIFIED_OVERLAYS,
        )
        self.assertEqual(state, "rollback_restart_pending")
        pending = self.control.load_web_activation_journal(
            self.root,
            "web_host_restart_pending_001",
            verified_artifacts=VERIFIED_ARTIFACTS,
            verified_overlays=VERIFIED_OVERLAYS,
        )
        self.assertEqual(pending.state, "rollback_restart_pending")

        with self.assertRaisesRegex(self.activation.WebActivationError, "verified sidecar readiness"):
            self.activation.finalize_web_activation_after_verified_sidecar_start(
                self.root,
                readiness={"ready": True, "service_count": 0},
                verified_artifacts=VERIFIED_ARTIFACTS,
                verified_overlays=VERIFIED_OVERLAYS,
            )

        outcome = self.activation.finalize_web_activation_after_verified_sidecar_start(
            self.root,
            readiness={"ready": True, "service_count": 1},
            verified_artifacts=VERIFIED_ARTIFACTS,
            verified_overlays=VERIFIED_OVERLAYS,
        )
        self.assertIsNotNone(outcome)
        self.assertTrue(outcome.rolled_back)
        journal = self.control.load_web_activation_journal(
            self.root,
            "web_host_restart_pending_001",
            verified_artifacts=VERIFIED_ARTIFACTS,
            verified_overlays=VERIFIED_OVERLAYS,
        )
        self.assertEqual(journal.state, "rolled_back")
        self.assertEqual(journal.readiness["rollback"]["service_count"], 1)


if __name__ == "__main__":
    unittest.main()
