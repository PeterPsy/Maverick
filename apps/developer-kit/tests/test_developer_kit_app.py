"""Tests for the Developer Kit app contract."""

from __future__ import annotations

from pathlib import Path
import unittest

from core.apps.contracts import parse_app_contract_file


class DeveloperKitAppTestCase(unittest.TestCase):
    def test_contract_parses(self) -> None:
        parsed = parse_app_contract_file(Path(__file__).resolve().parents[1])

        self.assertEqual(parsed.app_id, "developer-kit")
        self.assertIsNone(parsed.contract.entrypoints.backend)
        self.assertIsNone(parsed.contract.visibility.platform_roles)


if __name__ == "__main__":
    unittest.main()
