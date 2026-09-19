"""Sealed source contract and official SDK completeness."""

from __future__ import annotations

from pathlib import Path
import json
import unittest

from core.apps.contracts import parse_app_contract_file
from core.app_sdk.service import validate_app_source


class ExternalAppsContractTest(unittest.TestCase):
    def test_contract_parses(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        parsed = parse_app_contract_file(app_root)
        self.assertEqual(parsed.app_id, "external-apps")
        self.assertEqual(parsed.contract.distribution.mode, "sealed")
        self.assertEqual(parsed.contract.requires[0].alias, "static-exporter")
        contract = json.loads((app_root / "app_contract.json").read_text())
        self.assertEqual(contract["presentation"]["frontend_role"], "supporting")
        self.assertEqual(contract["provides"][0]["interface"], "external.surfaces.settings")
        self.assertEqual(contract["widgets"][0]["content_kinds"], ["shell.app.external.surfaces"])
        result = validate_app_source(app_root)
        self.assertTrue(result.valid, result.issues)


if __name__ == "__main__":
    unittest.main()
