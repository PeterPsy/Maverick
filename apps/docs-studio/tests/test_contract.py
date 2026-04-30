"""Generated contract smoke test."""

from __future__ import annotations

from pathlib import Path
import unittest

from core.apps.contracts import parse_app_contract_file


class GeneratedAppContractTest(unittest.TestCase):
    def test_contract_parses(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        parsed = parse_app_contract_file(app_root)
        self.assertEqual(parsed.app_id, "docs-studio")


if __name__ == "__main__":
    unittest.main()
