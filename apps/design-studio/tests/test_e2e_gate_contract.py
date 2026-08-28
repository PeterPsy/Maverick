"""The declared Design Studio E2E commands must resolve to maintained files."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


APP_ROOT = Path(__file__).resolve().parents[1]


class E2EGateContractTests(unittest.TestCase):
    def test_all_profiles_use_the_current_native_gate(self) -> None:
        package = json.loads((APP_ROOT / "package.json").read_text(encoding="utf-8"))
        scripts = package["scripts"]
        for name in (
            "test:e2e:quick",
            "test:e2e:affected",
            "test:e2e:release",
            "test:e2e:migration",
            "test:e2e:hosted",
        ):
            self.assertIn("tests/opendesign_e2e_gate.py", scripts[name])
        self.assertTrue((APP_ROOT / "tests/opendesign_e2e_gate.py").is_file())
        rendered = json.dumps(scripts)
        self.assertNotIn("opendesign_product.e2e.mjs", rendered)
        self.assertNotIn("smoke_opendesign_migration.py", rendered)
        self.assertNotIn("opendesign_hosted_smoke.e2e.mjs", rendered)


if __name__ == "__main__":
    unittest.main()
