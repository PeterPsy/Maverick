from __future__ import annotations

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
    _restart_sidecars,
    _run_gate,
    apply_incremental,
    classify_diff,
    resolve_changeset,
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

    def test_web_build_and_react_patches_never_imply_runtime_pipeline(self) -> None:
        result = classify_diff(
            [
                "apps/design-studio/service/patches/0002-maverick-web-build.patch",
                "apps/design-studio/service/patches/0003-maverick-web-react.patch",
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

    def test_release_profile_invokes_only_the_complete_e2e_profile(self) -> None:
        result = classify_diff(["apps/design-studio/frontend/src/App.tsx"], profile="release")

        self.assertIn("opendesign_e2e_release", result.actions)
        self.assertNotIn("opendesign_e2e_quick", result.actions)
        self.assertNotIn("opendesign_e2e_affected", result.actions)

    def test_restart_invocation_uses_operator_as_a_boolean_flag(self) -> None:
        completed = Mock(
            returncode=0,
            stdout=(
                '{"readiness":{"ready":true,"service_count":1},'
                '"event":{"type":"maverick.app.runtime-changed",'
                '"owner_app_id":"design-studio","resource":"runtime/frontend"}}'
            ),
        )
        with patch("opendesign_dev_apply.subprocess.run", return_value=completed) as run:
            readiness = _restart_sidecars({}, repo_root=Path("/repo"))

        command = run.call_args.args[0]
        self.assertEqual(command.count("--operator"), 1)
        self.assertNotIn("true", command)
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

    def test_apply_requires_one_explicit_changeset(self) -> None:
        with patch("opendesign_dev_apply._repo_root", return_value=Path("/repo")):
            with self.assertRaisesRegex(DevApplyError, "exactly one changeset"):
                apply_incremental({}, {"dry_run": True})

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


if __name__ == "__main__":
    unittest.main()
