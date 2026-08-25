from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


SERVICE_ROOT = Path(__file__).resolve().parents[1] / "service"
sys.path.insert(0, str(SERVICE_ROOT))

from opendesign_generation_control import (  # noqa: E402
    load_runtime_activation_journal,
    load_runtime_generation_control,
    write_generation_control,
    write_runtime_activation_journal,
)
from opendesign_generation_model import (  # noqa: E402
    GenerationControl,
    LaunchSelection,
    RuntimeActivationJournal,
)
from opendesign_runtime_activation import (  # noqa: E402
    RuntimeActivationError,
    activate_runtime_binding,
    finalize_runtime_activation_after_verified_sidecar_start,
    recover_runtime_activation,
    retry_runtime_activation_candidate,
)


OLD_RUNTIME = "a" * 64
NEW_RUNTIME = "b" * 64
OLD_WEB = "c" * 64
NEW_WEB = "d" * 64
VERIFIED_ARTIFACTS = {OLD_RUNTIME: "0.16.1", NEW_RUNTIME: "0.16.1"}
VERIFIED_OVERLAYS = {
    OLD_WEB: {"od_version": "0.16.1", "compatible_runtime_artifact_sha256": [OLD_RUNTIME]},
    NEW_WEB: {"od_version": "0.16.1", "compatible_runtime_artifact_sha256": [NEW_RUNTIME]},
}


class OpenDesignRuntimeActivationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory(prefix="maverick-runtime-activation-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "opendesign"
        for relative in (
            "instances/gen_active/data",
            "backups",
            "migrations",
            "web-activations",
            "runtime-activations",
        ):
            (self.root / relative).mkdir(parents=True)
        self.source = LaunchSelection(OLD_RUNTIME, OLD_WEB, "0.16.1", "gen_active")
        self.target = LaunchSelection(NEW_RUNTIME, NEW_WEB, "0.16.1", "gen_active")
        (self.root / "instances/gen_active/data/preserved.txt").write_text("preserved\n", encoding="utf-8")
        write_generation_control(
            self.root,
            GenerationControl(self.source, None, None, None, None, "2026-08-25T00:00:00Z"),
            verified_artifacts=VERIFIED_ARTIFACTS,
            verified_overlays=VERIFIED_OVERLAYS,
        )

    def test_activation_commits_same_generation_and_retains_runtime_rollback(self) -> None:
        outcome = activate_runtime_binding(
            self.root,
            target_runtime_artifact_sha256=NEW_RUNTIME,
            target_web_overlay_sha256=NEW_WEB,
            runtime_activation_id="runtime_unit_success",
            verified_artifacts=VERIFIED_ARTIFACTS,
            verified_overlays=VERIFIED_OVERLAYS,
            restart_sidecars=lambda: {"ready": True, "service_count": 1},
        )

        self.assertTrue(outcome.activated)
        self.assertEqual(outcome.control.active, self.target)
        self.assertEqual(outcome.control.previous_runtime, self.source)
        self.assertEqual(
            (self.root / "instances/gen_active/data/preserved.txt").read_text(encoding="utf-8"),
            "preserved\n",
        )
        journal = load_runtime_activation_journal(
            self.root,
            "runtime_unit_success",
            verified_artifacts=VERIFIED_ARTIFACTS,
            verified_overlays=VERIFIED_OVERLAYS,
        )
        self.assertEqual(journal.state, "ready_committed")

    def test_failed_candidate_restart_rolls_back_without_copying_data(self) -> None:
        calls = 0

        def restart():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("candidate failed")
            return {"ready": True, "service_count": 1}

        outcome = activate_runtime_binding(
            self.root,
            target_runtime_artifact_sha256=NEW_RUNTIME,
            target_web_overlay_sha256=NEW_WEB,
            runtime_activation_id="runtime_unit_rollback",
            verified_artifacts=VERIFIED_ARTIFACTS,
            verified_overlays=VERIFIED_OVERLAYS,
            restart_sidecars=restart,
        )

        self.assertTrue(outcome.rolled_back)
        self.assertEqual(outcome.control.active, self.source)
        self.assertEqual(outcome.control.previous_runtime, self.target)
        self.assertEqual(calls, 2)

    def test_crash_after_control_write_is_resumed_by_single_restart(self) -> None:
        journal = RuntimeActivationJournal(
            "runtime_unit_recovery",
            "prepared",
            self.source,
            self.target,
            {},
            None,
            "2026-08-25T00:01:00Z",
            "2026-08-25T00:01:00Z",
        )
        write_runtime_activation_journal(
            self.root,
            journal,
            verified_artifacts=VERIFIED_ARTIFACTS,
            verified_overlays=VERIFIED_OVERLAYS,
        )
        write_generation_control(
            self.root,
            GenerationControl(
                self.target,
                None,
                None,
                None,
                None,
                "2026-08-25T00:01:01Z",
                self.source,
                journal.runtime_activation_id,
            ),
            verified_artifacts=VERIFIED_ARTIFACTS,
            verified_overlays=VERIFIED_OVERLAYS,
        )
        calls = 0

        def restart():
            nonlocal calls
            calls += 1
            return {"ready": True, "service_count": 1}

        outcome = recover_runtime_activation(
            self.root,
            verified_artifacts=VERIFIED_ARTIFACTS,
            verified_overlays=VERIFIED_OVERLAYS,
            restart_sidecars=restart,
        )

        self.assertIsNotNone(outcome)
        self.assertTrue(outcome.activated)
        self.assertEqual(calls, 1)

    def test_rollback_pending_can_resume_the_exact_candidate_atomically(self) -> None:
        with self.assertRaises(RuntimeActivationError):
            activate_runtime_binding(
                self.root,
                target_runtime_artifact_sha256=NEW_RUNTIME,
                target_web_overlay_sha256=NEW_WEB,
                runtime_activation_id="runtime_unit_retry_candidate",
                verified_artifacts=VERIFIED_ARTIFACTS,
                verified_overlays=VERIFIED_OVERLAYS,
                restart_sidecars=lambda: (_ for _ in ()).throw(RuntimeError("not ready")),
            )

        outcome = retry_runtime_activation_candidate(
            self.root,
            runtime_activation_id="runtime_unit_retry_candidate",
            verified_artifacts=VERIFIED_ARTIFACTS,
            verified_overlays=VERIFIED_OVERLAYS,
            restart_sidecars=lambda: {"ready": True, "service_count": 1},
        )

        self.assertTrue(outcome.activated)
        self.assertFalse(outcome.rolled_back)
        self.assertEqual(outcome.control.active, self.target)
        journal = load_runtime_activation_journal(
            self.root,
            "runtime_unit_retry_candidate",
            verified_artifacts=VERIFIED_ARTIFACTS,
            verified_overlays=VERIFIED_OVERLAYS,
        )
        self.assertEqual(journal.state, "ready_committed")

    def test_launcher_finalization_requires_verified_readiness(self) -> None:
        activate_runtime_binding(
            self.root,
            target_runtime_artifact_sha256=NEW_RUNTIME,
            target_web_overlay_sha256=NEW_WEB,
            runtime_activation_id="runtime_unit_finalize",
            verified_artifacts=VERIFIED_ARTIFACTS,
            verified_overlays=VERIFIED_OVERLAYS,
            restart_sidecars=lambda: {"ready": True, "service_count": 1},
        )
        with self.assertRaisesRegex(RuntimeError, "verified sidecar"):
            finalize_runtime_activation_after_verified_sidecar_start(
                self.root,
                readiness={"ready": True, "service_count": 0},
                verified_artifacts=VERIFIED_ARTIFACTS,
                verified_overlays=VERIFIED_OVERLAYS,
            )
        control = load_runtime_generation_control(
            self.root,
            verified_artifacts=VERIFIED_ARTIFACTS,
            verified_overlays=VERIFIED_OVERLAYS,
        )
        self.assertEqual(control.active, self.target)

    def test_restart_callback_can_finalize_without_lock_convoy(self) -> None:
        def restart():
            finalized = finalize_runtime_activation_after_verified_sidecar_start(
                self.root,
                readiness={"ready": True, "service_count": 1},
                verified_artifacts=VERIFIED_ARTIFACTS,
                verified_overlays=VERIFIED_OVERLAYS,
            )
            self.assertIsNotNone(finalized)
            return {"ready": True, "service_count": 1}

        outcome = activate_runtime_binding(
            self.root,
            target_runtime_artifact_sha256=NEW_RUNTIME,
            target_web_overlay_sha256=NEW_WEB,
            runtime_activation_id="runtime_unit_no_convoy",
            verified_artifacts=VERIFIED_ARTIFACTS,
            verified_overlays=VERIFIED_OVERLAYS,
            restart_sidecars=restart,
        )

        self.assertTrue(outcome.activated)
        self.assertEqual(outcome.readiness["readiness_source"], "sidecar_health")

    def test_callback_failure_cannot_rollback_launcher_finalized_activation(self) -> None:
        def restart():
            finalized = finalize_runtime_activation_after_verified_sidecar_start(
                self.root,
                readiness={"ready": True, "service_count": 1},
                verified_artifacts=VERIFIED_ARTIFACTS,
                verified_overlays=VERIFIED_OVERLAYS,
            )
            self.assertIsNotNone(finalized)
            raise RuntimeError("core callback failed after launcher readiness")

        outcome = activate_runtime_binding(
            self.root,
            target_runtime_artifact_sha256=NEW_RUNTIME,
            target_web_overlay_sha256=NEW_WEB,
            runtime_activation_id="runtime_unit_launcher_won_race",
            verified_artifacts=VERIFIED_ARTIFACTS,
            verified_overlays=VERIFIED_OVERLAYS,
            restart_sidecars=restart,
        )

        self.assertTrue(outcome.activated)
        self.assertFalse(outcome.rolled_back)
        self.assertEqual(outcome.control.active, self.target)
        journal = load_runtime_activation_journal(
            self.root,
            "runtime_unit_launcher_won_race",
            verified_artifacts=VERIFIED_ARTIFACTS,
            verified_overlays=VERIFIED_OVERLAYS,
        )
        self.assertEqual(journal.state, "ready_committed")


if __name__ == "__main__":
    unittest.main()
