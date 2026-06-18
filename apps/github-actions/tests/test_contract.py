"""Generated contract smoke test."""

from __future__ import annotations

from pathlib import Path
import json
import unittest

from core.apps.contracts import parse_app_contract_file


class GeneratedAppContractTest(unittest.TestCase):
    def test_contract_parses(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        parsed = parse_app_contract_file(app_root)
        self.assertEqual(parsed.app_id, "github-actions")
        contract = json.loads((app_root / "app_contract.json").read_text())
        secret_reads = contract["permissions"]["secrets"]["read"]
        self.assertIn("github-app-id", secret_reads)
        self.assertIn("github-installation-id", secret_reads)
        self.assertIn("github-app-private-key", secret_reads)


if __name__ == "__main__":
    unittest.main()
