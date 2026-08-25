from __future__ import annotations

from contextlib import contextmanager, nullcontext
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


SERVICE_ROOT = Path(__file__).resolve().parents[1] / "service"
sys.path.insert(0, str(SERVICE_ROOT))

from opendesign_dev_apply import (  # noqa: E402
    DevApplyError,
    GateExecutionError,
    _changed_patch_series_components,
    _restart_sidecars,
    _run_gate,
    apply_incremental,
    classify_diff,
    materialize_changeset,
    resolve_changeset,
)
from opendesign_dev_changeset import (  # noqa: E402
    ChangeSet,
    _materialize_operational_inputs,
    materialize_immutable_tree,
)


class DevApplyClassifierTests(unittest.TestCase):
    def test_multiple_categories_union_every_required_gate(self) -> None:
        result = classify_diff(
            [
                "apps/design-studio/frontend/src/App.tsx",
                "apps/design-studio/backend/service.py",
                "apps/design-studio/service/patches/0003-maverick-web-react.patch",
                "core/api/sidecar_proxy.py",
            ]
        )

        self.assertEqual(
            set(result.actions),
            {
                "design_studio_frontend_tests",
                "design_studio_frontend_build",
                "design_studio_backend_tests",
                "opendesign_web_overlay",
                "app_hosting_core_tests",
                "opendesign_e2e_affected",
            },
        )
        self.assertFalse(result.conservative_elevation)

    def test_failed_gate_exposes_typed_redacted_diagnostic(self) -> None:
        completed = Mock(
            returncode=7,
            stdout="",
            stderr="OpenDesign OCI import failed at /home/private/signing-key.pem\n",
        )
        with tempfile.TemporaryDirectory(prefix="od-gate-error-") as temporary:
            root = Path(temporary)
            with patch("opendesign_dev_apply.subprocess.run", return_value=completed):
                with self.assertRaises(GateExecutionError) as raised:
                    _run_gate(
                        "design_studio_frontend_tests",
                        {},
                        repo_root=root,
                        changed_files=("apps/design-studio/frontend/src/App.tsx",),
                    )

        self.assertEqual(raised.exception.code, "design_studio_frontend_tests_failed")
        self.assertEqual(raised.exception.phase, "design_studio_frontend_tests")
        self.assertEqual(raised.exception.exit_code, 7)
        self.assertIn("<path>", raised.exception.diagnostic)
        self.assertNotIn("/home/private", raised.exception.diagnostic)

    def test_web_build_and_react_patches_never_imply_runtime_pipeline(self) -> None:
        result = classify_diff(
            [
                "apps/design-studio/service/patches/0002-maverick-web-build.patch",
                "apps/design-studio/service/patches/0003-maverick-web-react.patch",
                "apps/design-studio/service/patches/series.json",
            ]
        )
        self.assertIn("opendesign_web_overlay", result.actions)
        self.assertNotIn("opendesign_oci_pipeline", result.actions)

    def test_runtime_patch_implies_full_oci_pipeline(self) -> None:
        result = classify_diff(
            ["apps/design-studio/service/patches/0001-maverick-runtime-boundary.patch"]
        )
        self.assertIn("opendesign_oci_pipeline", result.actions)
        self.assertNotIn("opendesign_web_overlay", result.actions)

    def test_series_semantics_distinguish_web_digest_updates_from_runtime_updates(self) -> None:
        with tempfile.TemporaryDirectory(prefix="od-series-classification-") as temporary:
            root = Path(temporary)
            series_path = root / "apps/design-studio/service/patches/series.json"
            series_path.parent.mkdir(parents=True)
            (root / "AGENTS.md").write_text("guide\n", encoding="utf-8")
            baseline = {
                "schema_version": "2",
                "patches": [
                    {"component": "runtime", "sha256": "1" * 64},
                    {"component": "web-build", "sha256": "2" * 64},
                    {"component": "web-react", "sha256": "3" * 64},
                ],
            }
            series_path.write_text(json.dumps(baseline), encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)

            web_changed = json.loads(json.dumps(baseline))
            web_changed["patches"][1]["sha256"] = "4" * 64
            series_path.write_text(json.dumps(web_changed), encoding="utf-8")
            changeset = resolve_changeset(
                {"changed_files": ["apps/design-studio/service/patches/series.json"]},
                repo_root=root,
            )
            web_components = _changed_patch_series_components(changeset, repo_root=root)
            web_result = classify_diff(
                changeset.changed_files,
                series_components=web_components,
            )
            self.assertEqual(web_components, ("web-build",))
            self.assertIn("opendesign_web_overlay", web_result.actions)
            self.assertNotIn("opendesign_oci_pipeline", web_result.actions)

            runtime_changed = json.loads(json.dumps(baseline))
            runtime_changed["patches"][0]["sha256"] = "5" * 64
            series_path.write_text(json.dumps(runtime_changed), encoding="utf-8")
            changeset = resolve_changeset(
                {"changed_files": ["apps/design-studio/service/patches/series.json"]},
                repo_root=root,
            )
            runtime_components = _changed_patch_series_components(changeset, repo_root=root)
            runtime_result = classify_diff(
                changeset.changed_files,
                series_components=runtime_components,
            )
            self.assertEqual(runtime_components, ("runtime",))
            self.assertIn("opendesign_oci_pipeline", runtime_result.actions)
            self.assertNotIn("opendesign_web_overlay", runtime_result.actions)

    def test_unknown_file_elevates_to_complete_conservative_profile(self) -> None:
        result = classify_diff(["experimental/opaque-input.xyz"])
        self.assertTrue(result.conservative_elevation)
        self.assertEqual(result.unknown_files, ("experimental/opaque-input.xyz",))
        self.assertEqual(
            result.actions,
            (
                "design_studio_frontend_tests",
                "design_studio_frontend_build",
                "design_studio_backend_tests",
                "opendesign_web_overlay",
                "opendesign_oci_pipeline",
                "app_hosting_core_tests",
                "changed_suite",
                "opendesign_e2e_affected",
            ),
        )

    def test_frontend_backend_and_documentation_do_not_duplicate_unrelated_gates(self) -> None:
        frontend = classify_diff(["apps/design-studio/frontend/src/App.tsx"])
        backend = classify_diff(["apps/design-studio/backend/service.py"])
        readme = classify_diff(["apps/design-studio/README.md", "apps/design-studio/service/README.md"])

        self.assertEqual(
            frontend.actions,
            (
                "design_studio_frontend_tests",
                "design_studio_frontend_build",
                "opendesign_e2e_quick",
            ),
        )
        self.assertEqual(
            backend.actions,
            ("design_studio_backend_tests", "opendesign_e2e_affected"),
        )
        self.assertEqual(readme.actions, ())

        evidence = classify_diff(
            ["apps/design-studio/service/opendesign_change_to_live_benchmark_0_16_1.json"]
        )
        self.assertEqual(evidence.actions, ())

    def test_core_provider_change_uses_only_the_explicit_changed_suite(self) -> None:
        result = classify_diff(["core/providers/codex_runtime.py"])

        self.assertEqual(result.actions, ("changed_suite",))
        self.assertNotIn("app_hosting_core_tests", result.actions)

    def test_design_studio_hooks_use_backend_gate_without_repository_suite(self) -> None:
        result = classify_diff(["apps/design-studio/hooks/health_check.py"])

        self.assertEqual(
            result.actions,
            ("design_studio_backend_tests", "opendesign_e2e_affected"),
        )
        self.assertNotIn("changed_suite", result.actions)

    def test_hosting_support_paths_use_focused_hosting_gate(self) -> None:
        result = classify_diff(
            [
                "core/api/admin_api.py",
                "core/api/admin_app_management.py",
                "core/api/asgi_application.py",
                "core/api/platform_host.py",
                "core/api/server.py",
                "core/cli/app_commands.py",
                "core/shared/entrypoints.py",
                "tests/contracts/app_contract/test_services.py",
                "tests/unit/apps/test_surface_descriptors.py",
                "tests/unit/shared/test_entrypoints.py",
            ]
        )

        self.assertEqual(
            result.actions,
            ("app_hosting_core_tests", "opendesign_e2e_affected"),
        )
        self.assertNotIn("changed_suite", result.actions)

    def test_release_profile_invokes_only_the_complete_e2e_profile(self) -> None:
        result = classify_diff(["apps/design-studio/frontend/src/App.tsx"], profile="release")

        self.assertIn("opendesign_e2e_release", result.actions)
        self.assertNotIn("opendesign_e2e_quick", result.actions)
        self.assertNotIn("opendesign_e2e_affected", result.actions)

    def test_restart_invocation_targets_the_live_core_manager_control_channel(self) -> None:
        payload = {
            "readiness": {"ready": True, "service_count": 1},
            "event": {
                "type": "maverick.app.runtime-changed",
                "owner_app_id": "design-studio",
                "resource": "runtime/frontend",
            },
        }
        with patch("opendesign_dev_apply.request_sidecar_control", return_value=payload) as request:
            readiness = _restart_sidecars({}, repo_root=Path("/repo"))

        request.assert_called_once_with(
            Path("/repo"),
            operation="restart",
            workspace_id="default",
            app_id="design-studio",
            timeout_seconds=15,
        )
        self.assertEqual(readiness["ready"], True)
        self.assertTrue(readiness["browser_remount_event_emitted"])

    def test_changed_suite_receives_only_the_resolved_changeset_paths(self) -> None:
        completed = Mock(returncode=0, stdout="")
        with patch("opendesign_dev_apply.subprocess.run", return_value=completed) as run:
            result = _run_gate(
                "changed_suite",
                {},
                repo_root=Path("/repo"),
                changed_files=("apps/design-studio/backend/service.py",),
            )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(
            run.call_args.args[0],
            [
                sys.executable,
                "scripts/test_suite.py",
                "--changed",
                "--changed-path",
                "apps/design-studio/backend/service.py",
            ],
        )

    def test_e2e_gate_uses_verified_operational_python_and_browser_cache(self) -> None:
        with tempfile.TemporaryDirectory(prefix="od-e2e-closure-") as temporary:
            root = Path(temporary)
            snapshot = root / "snapshot"
            publish = root / "publish"
            playwright_package = snapshot / "apps/design-studio/node_modules/playwright/package.json"
            playwright_package.parent.mkdir(parents=True)
            playwright_package.write_text("{}\n", encoding="utf-8")
            python = publish / ".venv/bin/python"
            python.parent.mkdir(parents=True)
            python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            python.chmod(0o755)
            browsers = root / "browser-cache"
            browsers.mkdir()
            completed = Mock(returncode=0, stdout="")

            with patch("opendesign_dev_apply.subprocess.run", return_value=completed) as run:
                result = _run_gate(
                    "opendesign_e2e_affected",
                    {
                        "e2e_python": str(python),
                        "playwright_browsers_path": str(browsers),
                    },
                    repo_root=snapshot,
                    publish_repo_root=publish,
                    changed_files=("apps/design-studio/backend/service.py",),
                )

        self.assertEqual(result["status"], "passed")
        environment = run.call_args.kwargs["env"]
        self.assertEqual(environment["MAVERICK_OPENDESIGN_E2E_PYTHON"], str(python))
        self.assertEqual(environment["MAVERICK_PLAYWRIGHT_BROWSERS_PATH"], str(browsers))
        self.assertEqual(environment["PLAYWRIGHT_BROWSERS_PATH"], str(browsers))
        self.assertEqual(run.call_args.kwargs["cwd"], snapshot / "apps/design-studio")

    def test_e2e_gate_resolves_default_browser_cache_from_publishing_owner(self) -> None:
        with tempfile.TemporaryDirectory(prefix="od-e2e-default-closure-") as temporary:
            root = Path(temporary)
            snapshot = root / "snapshot"
            publish = root / "publish"
            publish.mkdir()
            playwright_package = snapshot / "apps/design-studio/node_modules/playwright/package.json"
            playwright_package.parent.mkdir(parents=True)
            playwright_package.write_text("{}\n", encoding="utf-8")
            python = publish / ".venv/bin/python"
            python.parent.mkdir(parents=True)
            python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            python.chmod(0o755)
            host_home = root / "host-home"
            browsers = host_home / ".cache/ms-playwright"
            browsers.mkdir(parents=True)
            agent_home = root / "agent-home"
            agent_home.mkdir()
            completed = Mock(returncode=0, stdout="")

            with (
                patch.dict("os.environ", {"HOME": str(agent_home)}, clear=True),
                patch(
                    "opendesign_dev_apply.pwd.getpwuid",
                    return_value=Mock(pw_dir=str(host_home)),
                ),
                patch("opendesign_dev_apply.subprocess.run", return_value=completed) as run,
            ):
                result = _run_gate(
                    "opendesign_e2e_affected",
                    {},
                    repo_root=snapshot,
                    publish_repo_root=publish,
                    changed_files=("apps/design-studio/backend/service.py",),
                )

        self.assertEqual(result["status"], "passed")
        environment = run.call_args.kwargs["env"]
        self.assertEqual(environment["HOME"], str(agent_home))
        self.assertEqual(environment["MAVERICK_PLAYWRIGHT_BROWSERS_PATH"], str(browsers))
        self.assertEqual(environment["PLAYWRIGHT_BROWSERS_PATH"], str(browsers))

    def test_apply_requires_one_explicit_changeset(self) -> None:
        with patch("opendesign_dev_apply._repo_root", return_value=Path("/repo")):
            with self.assertRaisesRegex(DevApplyError, "exactly one changeset"):
                apply_incremental({}, {"dry_run": True})

    def test_post_activation_gate_failure_automatically_restores_previous_overlay(self) -> None:
        changeset = ChangeSet(
            source="explicit_paths",
            changed_files=("apps/design-studio/service/patches/0003-maverick-web-react.patch",),
            base_sha=None,
            head_sha=None,
            path_sha256={
                "apps/design-studio/service/patches/0003-maverick-web-react.patch": "1" * 64
            },
        )
        overlay_result = {
            "status": "passed",
            "derivations": 1,
            "reproducible": False,
            "digests": {"runtime_artifact_sha256": "a" * 64, "web_overlay_sha256": "b" * 64},
            "cache": {},
            "readiness": {"ready": True},
            "rollback": {"performed": False},
            "change_to_live": {
                "previous_web_overlay_sha256": "c" * 64,
                "candidate_web_overlay_sha256": "b" * 64,
                "overlay_changed": True,
                "activated": True,
            },
        }
        with (
            patch("opendesign_dev_apply._repo_root", return_value=Path("/repo")),
            patch("opendesign_dev_apply.resolve_changeset", return_value=changeset),
            patch("opendesign_dev_apply._resolve_commit", return_value="d" * 40),
            patch("opendesign_dev_apply.materialize_changeset", return_value=nullcontext(Path("/snapshot"))),
            patch("opendesign_dev_apply._build_and_activate_overlay", return_value=overlay_result),
            patch("opendesign_dev_apply._run_gate", side_effect=RuntimeError("e2e regression")),
            patch(
                "opendesign_dev_apply._rollback_after_post_activation_failure",
                return_value={"performed": True, "status": "passed"},
            ) as rollback,
        ):
            with self.assertRaises(DevApplyError) as raised:
                apply_incremental({}, {"changed_files": list(changeset.changed_files)})

        rollback.assert_called_once()
        self.assertTrue(raised.exception.report["rollback"]["performed"])

    def test_default_web_cache_survives_materialized_checkout_cleanup(self) -> None:
        changeset = ChangeSet(
            source="explicit_paths",
            changed_files=("apps/design-studio/service/patches/0003-maverick-web-react.patch",),
            base_sha=None,
            head_sha=None,
            path_sha256={
                "apps/design-studio/service/patches/0003-maverick-web-react.patch": "1" * 64
            },
        )
        overlay_result = {
            "status": "passed",
            "derivations": 1,
            "reproducible": False,
            "digests": {"runtime_artifact_sha256": "a" * 64, "web_overlay_sha256": "b" * 64},
            "cache": {},
            "readiness": {"ready": True},
            "rollback": {"performed": False},
            "change_to_live": {
                "previous_web_overlay_sha256": "b" * 64,
                "candidate_web_overlay_sha256": "b" * 64,
                "overlay_changed": False,
                "activated": False,
            },
        }
        observed: dict[str, Path] = {}
        with tempfile.TemporaryDirectory(prefix="od-cache-persistence-") as temporary:
            root = Path(temporary) / "publish"
            root.mkdir()

            @contextmanager
            def isolated_checkout(*_args):
                with tempfile.TemporaryDirectory(prefix="snapshot-", dir=temporary) as snapshot_raw:
                    snapshot = Path(snapshot_raw)
                    observed["snapshot"] = snapshot
                    yield snapshot

            def build_overlay(*_args, cache_root: Path, **_kwargs):
                observed["cache"] = cache_root
                cache_root.mkdir(parents=True)
                (cache_root / "persistent.marker").write_text("cached\n", encoding="utf-8")
                return dict(overlay_result)

            with (
                patch("opendesign_dev_apply._repo_root", return_value=root),
                patch("opendesign_dev_apply.resolve_changeset", return_value=changeset),
                patch("opendesign_dev_apply._resolve_commit", return_value="d" * 40),
                patch("opendesign_dev_apply.materialize_changeset", side_effect=isolated_checkout),
                patch("opendesign_dev_apply._assert_changeset_unchanged"),
                patch("opendesign_dev_apply._build_and_activate_overlay", side_effect=build_overlay),
                patch("opendesign_dev_apply._run_gate", return_value={"status": "passed"}),
            ):
                report = apply_incremental({}, {"changed_files": list(changeset.changed_files)})

            expected_cache = root / "tmp/opendesign-web-cache"
            self.assertTrue(report["ok"])
            self.assertEqual(observed["cache"], expected_cache)
            self.assertFalse(observed["snapshot"].exists())
            self.assertTrue((expected_cache / "persistent.marker").is_file())

    def test_git_range_sees_committed_work_and_ignores_concurrent_dirty_paths(self) -> None:
        with tempfile.TemporaryDirectory(prefix="od-dev-changeset-") as temporary:
            root = Path(temporary)
            (root / "apps/design-studio").mkdir(parents=True)
            (root / "core/providers").mkdir(parents=True)
            (root / "AGENTS.md").write_text("guide\n", encoding="utf-8")
            readme = root / "apps/design-studio/README.md"
            readme.write_text("before\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
            base = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=True
            ).stdout.strip()
            readme.write_text("after\n", encoding="utf-8")
            subprocess.run(["git", "add", str(readme.relative_to(root))], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "task"], cwd=root, check=True)
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=True
            ).stdout.strip()
            (root / "core/providers/concurrent.py").write_text("dirty = True\n", encoding="utf-8")

            changeset = resolve_changeset({"base_sha": base, "head_sha": head}, repo_root=root)

        self.assertEqual(changeset.source, "git_range")
        self.assertEqual(changeset.changed_files, ("apps/design-studio/README.md",))

    def test_git_range_includes_committed_deletions(self) -> None:
        with tempfile.TemporaryDirectory(prefix="od-dev-deletion-") as temporary:
            root = Path(temporary)
            (root / "apps/design-studio").mkdir(parents=True)
            (root / "AGENTS.md").write_text("guide\n", encoding="utf-8")
            removed = root / "apps/design-studio/removed.md"
            removed.write_text("remove me\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
            base = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=True
            ).stdout.strip()
            removed.unlink()
            subprocess.run(["git", "add", "-u"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "delete"], cwd=root, check=True)
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=True
            ).stdout.strip()

            changeset = resolve_changeset({"base_sha": base, "head_sha": head}, repo_root=root)

        self.assertEqual(changeset.changed_files, ("apps/design-studio/removed.md",))
        self.assertIsNone(changeset.path_sha256["apps/design-studio/removed.md"])

    def test_materialized_changeset_excludes_undeclared_shared_worktree_changes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="od-materialized-checkout-") as temporary:
            root = Path(temporary)
            target = root / "apps/design-studio/backend/service.py"
            unrelated = root / "core/providers/runtime.py"
            target.parent.mkdir(parents=True)
            unrelated.parent.mkdir(parents=True)
            (root / "AGENTS.md").write_text("guide\n", encoding="utf-8")
            target.write_text("value = 'before'\n", encoding="utf-8")
            unrelated.write_text("value = 'committed'\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
            target.write_text("value = 'declared'\n", encoding="utf-8")
            unrelated.write_text("value = 'concurrent'\n", encoding="utf-8")
            untracked = root / "core/providers/concurrent.py"
            untracked.write_text("value = True\n", encoding="utf-8")
            changeset = resolve_changeset(
                {"changed_files": ["apps/design-studio/backend/service.py"]},
                repo_root=root,
            )

            with materialize_changeset(root, changeset) as snapshot:
                self.assertEqual(
                    (snapshot / "apps/design-studio/backend/service.py").read_text(encoding="utf-8"),
                    "value = 'declared'\n",
                )
                self.assertEqual(
                    (snapshot / "core/providers/runtime.py").read_text(encoding="utf-8"),
                    "value = 'committed'\n",
                )
                self.assertFalse((snapshot / "core/providers/concurrent.py").exists())

    def test_immutable_operational_tree_uses_independent_real_snapshot_paths(self) -> None:
        with tempfile.TemporaryDirectory(prefix="od-operational-tree-") as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "snapshot/vendor"
            payload = source / "digest/manifest.json"
            payload.parent.mkdir(parents=True)
            payload.write_text('{"verified":true}\n', encoding="utf-8")

            materialize_immutable_tree(source, destination)

            copied = destination / "digest/manifest.json"
            self.assertTrue(copied.is_file())
            self.assertFalse(destination.is_symlink())
            self.assertFalse(copied.is_symlink())
            self.assertEqual(copied.read_bytes(), payload.read_bytes())
            self.assertNotEqual(copied.stat().st_ino, payload.stat().st_ino)

            copied.chmod(0o644)
            copied.write_text('{"verified":false}\n', encoding="utf-8")

            self.assertEqual(payload.read_text(encoding="utf-8"), '{"verified":true}\n')

    def test_operational_snapshot_never_copies_repository_vendor_artifacts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="od-operational-selection-") as temporary:
            root = Path(temporary) / "repository"
            snapshot = Path(temporary) / "snapshot"
            service = root / "apps/design-studio/service"
            snapshot_service = snapshot / "apps/design-studio/service"
            service.mkdir(parents=True)
            snapshot_service.mkdir(parents=True)
            vendor_files = (
                service / "vendor/open-design" / ("a" * 64) / "runtime.txt",
                service / "vendor/open-design-web" / ("b" * 64) / "web.txt",
            )
            for path in vendor_files:
                path.parent.mkdir(parents=True)
                path.write_text(f"{path.name}\n", encoding="utf-8")

            _materialize_operational_inputs(root, snapshot)

            self.assertFalse((snapshot_service / "vendor").exists())


if __name__ == "__main__":
    unittest.main()
