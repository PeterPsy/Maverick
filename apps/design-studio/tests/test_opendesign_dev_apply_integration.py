from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[3]
SERVICE_ROOT = ROOT / "apps/design-studio/service"
sys.path.insert(0, str(SERVICE_ROOT))

from opendesign_dev_apply import _run_gate  # noqa: E402
from opendesign_dev_changeset import materialize_changeset, resolve_changeset  # noqa: E402


class DevApplyIsolatedGateIntegrationTests(unittest.TestCase):
    def test_real_quick_e2e_runs_from_materialized_checkout(self) -> None:
        changed_files = (
            "apps/design-studio/service/opendesign_launcher.py",
            "apps/design-studio/service/opendesign_web_activation.py",
            "apps/design-studio/tests/opendesign_product.e2e.mjs",
        )
        changeset = resolve_changeset({"changed_files": list(changed_files)}, repo_root=ROOT)

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
