"""Architecture proof for the selected generic runtime-stream boundary."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
APP_ROOT = Path(__file__).resolve().parents[1]
CORE_BRIDGE_FILES = (
    "core/runtime/app_streams.py",
    "core/runtime/store.py",
    "core/apps/runtime_root_capabilities.py",
    "core/apps/runtime_requests.py",
    "core/api/platform_state.py",
    "core/api/sidecar_core_routes.py",
    "core/apps/runtime_event_hooks.py",
    "core/api/app_runtime_cleanup_requests.py",
    "core/recovery/backend_restart.py",
)


class DesignStudioRuntimeBridgeArchitectureProof(unittest.TestCase):
    def test_generic_core_has_no_opendesign_product_knowledge(self) -> None:
        forbidden = (
            "design-studio",
            "design_studio",
            "opendesign",
            "open-design",
            "/api/runs",
            "od_run",
            "od_project",
        )
        violations: list[str] = []
        for relative_path in CORE_BRIDGE_FILES:
            text = (REPO_ROOT / relative_path).read_text(encoding="utf-8").lower()
            for marker in forbidden:
                if marker in text:
                    violations.append(f"{relative_path}: {marker}")
        self.assertEqual(violations, [])

    def test_product_routes_and_translation_remain_app_owned(self) -> None:
        contract = json.loads((APP_ROOT / "app_contract.json").read_text(encoding="utf-8"))
        sidecar = contract["services"]["http_sidecars"][0]
        handled = {
            (rule["method"], rule["path_template"])
            for rule in sidecar["proxy"]["route_policy"]["handled_by_core"]
        }
        self.assertTrue(contract["permissions"]["runtime"]["create_sessions"])
        self.assertTrue(contract["permissions"]["runtime"]["cleanup_sessions"])
        self.assertEqual(contract["entrypoints"]["hooks"]["runtime_event"], "backend/app_backend.py")
        self.assertTrue(
            {
                ("POST", "/api/runs"),
                ("GET", "/api/runs/{id}/events"),
                ("POST", "/api/runs/{id}/cancel"),
                ("GET", "/api/runs/{id}/result-package"),
            }.issubset(handled)
        )
        translator = (APP_ROOT / "backend" / "runtime_bridge.py").read_text(encoding="utf-8")
        self.assertIn("open-design.run-result-package.v1", translator)
        self.assertIn('name, data = "agent"', translator)
        self.assertIn('name, data = "end"', translator)

    def test_adr_records_option_b_as_implemented(self) -> None:
        adr = (REPO_ROOT / "docs" / "architecture" / "design_studio_runtime_bridge.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("Status: Implemented (G3 + WP7)", adr)
        self.assertIn("Decision: option B", adr)
        self.assertIn("Core source contains no", adr)


if __name__ == "__main__":
    unittest.main()
