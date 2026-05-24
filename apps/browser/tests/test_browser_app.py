from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from core.apps.contracts import parse_app_contract_file


APP_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = APP_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from service import handle_action, mcp_result_for_tool
from store import load_state


class BrowserAppTests(unittest.TestCase):
    def test_contract_declares_sealed_p0_browser_surfaces(self) -> None:
        parsed = parse_app_contract_file(APP_ROOT)

        self.assertEqual(parsed.app_id, "browser")
        self.assertEqual(parsed.contract.distribution.mode, "sealed")
        self.assertEqual(parsed.contract.distribution.source_access, "none")
        self.assertEqual(parsed.contract.presentation.frontend_role, "workspace")
        self.assertEqual(parsed.contract.compatibility.supported_workspace_modes, ["full-access"])
        self.assertEqual(parsed.contract.storage.primary_paths, ["data/browser/state.json"])
        self.assertIn("browser_navigate", parsed.contract.capabilities.mcp_tools)
        self.assertIn("browser_click", parsed.contract.capabilities.mcp_tools)
        self.assertNotIn("browser_evaluate", parsed.contract.capabilities.mcp_tools)
        self.assertNotIn("browser_run_code", parsed.contract.capabilities.mcp_tools)

    def test_policy_preflight_uses_core_browser_egress_policy(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir)
            denied_status, denied = handle_action(data_root, {"action": "policy.preflight", "url": "file:///etc/passwd"})
            dev_status, dev = handle_action(
                data_root,
                {
                    "action": "policy.preflight",
                    "url": "http://hostmachine:8000/apps/base-shell/",
                    "mode": "maverick_dev_inspector",
                },
            )

        self.assertEqual(denied_status, 200)
        self.assertFalse(denied["policy"]["allowed"])
        self.assertEqual(denied["policy"]["reason"], "blocked_disallowed_scheme")
        self.assertEqual(dev_status, 200)
        self.assertTrue(dev["policy"]["allowed"])
        self.assertEqual(dev["policy"]["reason"], "allowed_admin_dev_target")

    def test_navigation_denial_is_audited_before_broker_handoff(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir)
            status_code, result = handle_action(data_root, {"action": "navigate", "url": "http://169.254.169.254/latest/meta-data/"})
            state = load_state(str(data_root))

        self.assertEqual(status_code, 403)
        self.assertEqual(result["error"], "policy_denied")
        self.assertEqual(state["audit"][-1]["action"], "navigate")
        self.assertEqual(state["audit"][-1]["status"], "denied")

    def test_dev_inspector_click_is_policy_checked_then_blocks_on_missing_broker(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir)
            status_code, result = mcp_result_for_tool(
                data_root,
                "browser_click",
                {
                    "session_id": "session-1",
                    "ref": "button-1",
                    "target_url": "http://hostmachine:8000/app/chat",
                    "mode": "maverick_dev_inspector",
                },
            )
            state = load_state(str(data_root))

        self.assertEqual(status_code, 503)
        self.assertEqual(result["error"], "broker_unavailable")
        self.assertEqual(state["audit"][-1]["action"], "click")
        self.assertEqual(state["audit"][-1]["status"], "blocked")

    def test_install_hook_creates_state_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir)
            completed = subprocess.run(
                [sys.executable, str(APP_ROOT / "hooks" / "install.py")],
                input=json.dumps({"data_root": str(data_root)}),
                text=True,
                capture_output=True,
                check=True,
                cwd=str(APP_ROOT),
            )
            output = json.loads(completed.stdout)

            self.assertEqual(output["status"], "ok")
            self.assertTrue((data_root / "state.json").is_file())


if __name__ == "__main__":
    unittest.main()
