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

    def test_release_gate_contains_real_native_product_and_browser_proofs(self) -> None:
        gate = (APP_ROOT / "tests/opendesign_e2e_gate.py").read_text(encoding="utf-8")
        product = (APP_ROOT / "service/smoke_native_product.py").read_text(encoding="utf-8")

        self.assertIn("smoke_native_product.py", gate)
        self.assertIn("native_deep_link.e2e.mjs", gate)
        self.assertTrue((APP_ROOT / "service/smoke_native_product.py").is_file())
        self.assertTrue((APP_ROOT / "tests/native_deep_link.e2e.mjs").is_file())
        self.assertNotIn("_write_wrappers", product)
        self.assertIn('agent_id=CLI_AGENT_ID', product)
        self.assertIn("_prove_official_cli_cancellation", product)
        for proof in (
            "cross_asset_denied",
            "cross_model_denied",
            "cross_capability_denied",
            "api_tools_media",
            "cli_tools_media",
        ):
            self.assertIn(proof, product)

    def test_contract_version_forces_existing_installations_through_upgrade_hook(self) -> None:
        contract = json.loads((APP_ROOT / "app_contract.json").read_text(encoding="utf-8"))

        self.assertGreaterEqual(
            tuple(int(part) for part in contract["version"].split(".")),
            (0, 5, 4),
        )


if __name__ == "__main__":
    unittest.main()
