from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
SERVICE_ROOT = ROOT / "apps/design-studio/service"
sys.path.insert(0, str(SERVICE_ROOT))

from opendesign_dev_apply import _run_gate  # noqa: E402
from opendesign_dev_changeset import materialize_changeset, resolve_changeset  # noqa: E402


class DevApplyIsolatedGateIntegrationTests(unittest.TestCase):
    def test_real_quick_e2e_runs_from_materialized_checkout(self) -> None:
        committed_release = subprocess.run(
            [
                "git",
                "cat-file",
                "-e",
                "HEAD:apps/design-studio/service/opendesign_release_selection.json",
            ],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if committed_release.returncode != 0:
            self.skipTest(
                "the isolated gate requires the protected-store release baseline to be committed"
            )
        changed_files = (
            "apps/design-studio/service/opendesign_launcher.py",
            "apps/design-studio/service/opendesign_web_activation.py",
            "apps/design-studio/tests/opendesign_product.e2e.mjs",
        )
        changeset = resolve_changeset({"changed_files": list(changed_files)}, repo_root=ROOT)

        with tempfile.TemporaryDirectory(prefix="mav-agent-home-") as agent_home:
            with patch.dict(os.environ, {"HOME": agent_home}):
                for variable in (
                    "MAVERICK_PLAYWRIGHT_BROWSERS_PATH",
                    "PLAYWRIGHT_BROWSERS_PATH",
                ):
                    os.environ.pop(variable, None)
                with materialize_changeset(ROOT, changeset) as snapshot:
                    result = _run_gate(
                        "opendesign_e2e_quick",
                        {},
                        repo_root=snapshot,
                        publish_repo_root=ROOT,
                        changed_files=changed_files,
                    )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["exit_code"], 0)


if __name__ == "__main__":
    unittest.main()
