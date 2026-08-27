"""Global protected-store reference, audit-coverage, and GC proofs."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
from threading import Event, Thread
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[3]
SERVICE_ROOT = ROOT / "apps/design-studio/service"
sys.path.insert(0, str(SERVICE_ROOT))

from opendesign_artifact_operations import (  # noqa: E402
    ArtifactStoreError,
    RequiredArtifacts,
    _garbage_collect,
    _global_required_artifacts,
    _validate_runtime_web_bindings,
    _workspace_reference_lock,
    discover_design_studio_workspace_data_roots,
)
from opendesign_generation_control import (  # noqa: E402
    GenerationControlError,
    _validate_live_artifact_references,
    _workspace_reference_write_lock,
)
from opendesign_generation_model import GenerationControl, LaunchSelection  # noqa: E402


CURRENT = "a" * 64
ROLLBACK = "b" * 64
ALPHA_RUNTIME = "c" * 64
BRAVO_RUNTIME = "d" * 64
ALPHA_WEB = "e" * 64
BRAVO_WEB = "f" * 64


class OpenDesignMultiWorkspaceArtifactTests(unittest.TestCase):
    def test_global_reference_snapshot_unions_every_workspace(self) -> None:
        with tempfile.TemporaryDirectory(prefix="od-global-references-") as temporary:
            repository = self._repository(Path(temporary), "alpha", "bravo")
            requirements = {
                "alpha": self._required(ALPHA_RUNTIME, ALPHA_WEB, optional=("1" * 64,)),
                "bravo": self._required(BRAVO_RUNTIME, BRAVO_WEB, optional=("2" * 64,)),
            }

            def local(data_root: Path, *, manifest):
                del manifest
                return requirements[data_root.parents[1].name]

            with patch(
                "opendesign_artifact_operations._required_artifacts",
                side_effect=local,
            ):
                first = _global_required_artifacts(
                    repository,
                    requested_workspace_id="alpha",
                    manifest={},
                )
                requirements["bravo"] = self._required("3" * 64, BRAVO_WEB)
                changed = _global_required_artifacts(
                    repository,
                    requested_workspace_id="alpha",
                    manifest={},
                )

        self.assertEqual(first.workspace_ids, ("alpha", "bravo"))
        self.assertEqual(
            set(first.required_runtime_artifacts),
            {
                CURRENT,
                ROLLBACK,
                ALPHA_RUNTIME,
                BRAVO_RUNTIME,
                "1" * 64,
                "2" * 64,
            },
        )
        self.assertEqual(first.optional_runtime, ())
        self.assertEqual(set(first.web_overlays), {ALPHA_WEB, BRAVO_WEB})
        self.assertEqual(
            set(first.runtime_web_bindings),
            {(ALPHA_RUNTIME, ALPHA_WEB), (BRAVO_RUNTIME, BRAVO_WEB)},
        )
        self.assertNotEqual(
            first.workspace_reference_sha256,
            changed.workspace_reference_sha256,
        )

    def test_gc_keeps_digest_referenced_only_by_another_workspace(self) -> None:
        with tempfile.TemporaryDirectory(prefix="od-global-gc-") as temporary:
            root = Path(temporary)
            for relative in (
                "runtime",
                "web",
                "quarantine/runtime",
                "quarantine/web",
                "quarantine/staging",
            ):
                (root / relative).mkdir(parents=True)
            unreferenced_runtime = "9" * 64
            unreferenced_web = "8" * 64
            for digest in (CURRENT, ROLLBACK, ALPHA_RUNTIME, BRAVO_RUNTIME, unreferenced_runtime):
                (root / "runtime" / digest).mkdir()
            for digest in (ALPHA_WEB, BRAVO_WEB, unreferenced_web):
                (root / "web" / digest).mkdir()
            store = Mock()
            store.root = root
            store.recover_orphaned_staging.return_value = {
                "recovered": 0,
                "active": 0,
                "deferred_legacy": 0,
            }
            required = RequiredArtifacts(
                current_runtime=CURRENT,
                active_runtime=ALPHA_RUNTIME,
                rollback_runtime=ROLLBACK,
                active_web=ALPHA_WEB,
                optional_runtime=(),
                web_overlays=(ALPHA_WEB, BRAVO_WEB),
                fresh_web_overlay=ALPHA_WEB,
                required_runtime_artifacts=(
                    CURRENT,
                    ROLLBACK,
                    ALPHA_RUNTIME,
                    BRAVO_RUNTIME,
                ),
                workspace_ids=("alpha", "bravo"),
                workspace_reference_sha256="7" * 64,
            )
            with (
                patch(
                    "opendesign_artifact_operations._read_selection",
                    return_value={"quarantine_retention_days": 14},
                ),
                patch("opendesign_artifact_operations._purge_expired_quarantine"),
            ):
                result = _garbage_collect(store, required=required)

            self.assertTrue((root / "runtime" / BRAVO_RUNTIME).is_dir())
            self.assertTrue((root / "web" / BRAVO_WEB).is_dir())
            self.assertEqual(
                result["marked_for_gc"],
                [f"runtime:{unreferenced_runtime}", f"web:{unreferenced_web}"],
            )

    def test_workspace_registry_symlink_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="od-global-symlink-") as temporary:
            repository = self._repository(Path(temporary), "alpha")
            external = Path(temporary) / "external"
            external.mkdir()
            (repository / "workspaces/bravo").symlink_to(external, target_is_directory=True)
            with self.assertRaises(ArtifactStoreError) as raised:
                discover_design_studio_workspace_data_roots(
                    repository,
                    requested_workspace_id="alpha",
                )
        self.assertEqual(raised.exception.phase, "workspace_reference_scan")

    def test_global_audit_validates_each_workspace_runtime_web_pair(self) -> None:
        required = RequiredArtifacts(
            current_runtime=CURRENT,
            active_runtime=ALPHA_RUNTIME,
            rollback_runtime=ROLLBACK,
            active_web=ALPHA_WEB,
            optional_runtime=(),
            web_overlays=(ALPHA_WEB, BRAVO_WEB),
            fresh_web_overlay=ALPHA_WEB,
            runtime_web_bindings=(
                (ALPHA_RUNTIME, ALPHA_WEB),
                (BRAVO_RUNTIME, BRAVO_WEB),
            ),
        )
        store = Mock()
        store.fast_web_overlay.side_effect = [Mock(), ArtifactStoreError(
            "runtime_binding_invalid",
            "artifact_fast_verify",
            "incompatible binding",
        )]

        with self.assertRaises(ArtifactStoreError):
            _validate_runtime_web_bindings(store, required=required)

        self.assertEqual(
            [call.kwargs["runtime_artifact_sha256"] for call in store.fast_web_overlay.call_args_list],
            [ALPHA_RUNTIME, BRAVO_RUNTIME],
        )

    def test_gc_reference_scan_serializes_control_commits(self) -> None:
        with tempfile.TemporaryDirectory(prefix="od-global-reference-lock-") as temporary:
            store_root = Path(temporary) / "store"
            namespace = store_root / "design-studio/opendesign"
            locks = namespace / ".locks"
            locks.mkdir(parents=True)
            lock = locks / "workspace-references.lock"
            lock.touch(mode=0o444)
            lock.chmod(0o444)
            store = Mock(root=namespace)
            entered = Event()

            def write_control() -> None:
                with _workspace_reference_write_lock():
                    entered.set()

            with patch.dict(
                "os.environ",
                {"MAVERICK_APP_ARTIFACT_STORE_ROOT": str(store_root)},
            ):
                with _workspace_reference_lock(store, exclusive=True):
                    writer = Thread(target=write_control)
                    writer.start()
                    self.assertFalse(entered.wait(0.05))
                writer.join(timeout=2)

            self.assertFalse(writer.is_alive())
            self.assertTrue(entered.is_set())

    def test_control_commit_rechecks_packages_after_acquiring_gc_lock(self) -> None:
        with tempfile.TemporaryDirectory(prefix="od-control-live-reference-") as temporary:
            namespace = Path(temporary)
            (namespace / "runtime" / ALPHA_RUNTIME).mkdir(parents=True)
            selection = LaunchSelection(
                ALPHA_RUNTIME,
                ALPHA_WEB,
                "0.16.1",
                "generation_alpha",
            )
            control = GenerationControl(
                selection,
                None,
                None,
                None,
                None,
                "2026-08-27T00:00:00Z",
            )

            with self.assertRaisesRegex(GenerationControlError, "web artifact disappeared"):
                _validate_live_artifact_references(namespace, control)

            (namespace / "web" / ALPHA_WEB).mkdir(parents=True)
            _validate_live_artifact_references(namespace, control)

    @staticmethod
    def _required(active_runtime: str, active_web: str, *, optional=()) -> RequiredArtifacts:
        return RequiredArtifacts(
            current_runtime=CURRENT,
            active_runtime=active_runtime,
            rollback_runtime=ROLLBACK,
            active_web=active_web,
            optional_runtime=tuple(optional),
            web_overlays=(active_web,),
            fresh_web_overlay=ALPHA_WEB,
            runtime_web_bindings=((active_runtime, active_web),),
        )

    @staticmethod
    def _repository(parent: Path, *workspace_ids: str) -> Path:
        root = parent / "maverick"
        for relative in ("apps", "core", "workspaces"):
            (root / relative).mkdir(parents=True)
        (root / "AGENTS.md").write_text("", encoding="utf-8")
        for workspace_id in workspace_ids:
            (root / "workspaces" / workspace_id / "data/design-studio").mkdir(parents=True)
        return root


if __name__ == "__main__":
    unittest.main()
