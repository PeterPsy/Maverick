from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch


SERVICE_ROOT = Path(__file__).resolve().parents[1] / "service"
sys.path.insert(0, str(SERVICE_ROOT))

from opendesign_dev_apply import _restart_sidecars, classify_diff  # noqa: E402


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
                "changed_suite",
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
            ),
        )

    def test_restart_invocation_uses_operator_as_a_boolean_flag(self) -> None:
        completed = Mock(
            returncode=0,
            stdout='{"readiness":{"ready":true,"service_count":1}}',
        )
        with patch("opendesign_dev_apply.subprocess.run", return_value=completed) as run:
            readiness = _restart_sidecars({}, repo_root=Path("/repo"))

        command = run.call_args.args[0]
        self.assertEqual(command.count("--operator"), 1)
        self.assertNotIn("true", command)
        self.assertEqual(readiness["ready"], True)


if __name__ == "__main__":
    unittest.main()
