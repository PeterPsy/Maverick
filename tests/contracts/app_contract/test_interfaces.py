"""Generic app interface contract checks for the core resolver."""

from __future__ import annotations

from pathlib import Path
import unittest

from core.apps.contracts import parse_app_contract_file


REPO_ROOT = Path(__file__).resolve().parents[3]


class AppInterfaceContractTestCase(unittest.TestCase):
    def test_app_interface_declarations_are_structurally_resolvable(self) -> None:
        for contract_path in sorted((REPO_ROOT / "apps").glob("*/app_contract.json")):
            with self.subTest(app=contract_path.parent.name):
                parsed = parse_app_contract_file(contract_path.parent)
                provided = [item.interface for item in parsed.contract.provides]
                required_aliases = [item.alias for item in parsed.contract.requires]
                self.assertEqual(len(provided), len(set(provided)))
                self.assertEqual(len(required_aliases), len(set(required_aliases)))
                self.assertNotIn("", provided)
                self.assertNotIn("", required_aliases)

    def test_workspace_app_interface_declarations_are_structurally_resolvable(self) -> None:
        for contract_path in sorted((REPO_ROOT / "workspaces").glob("*/apps/*/app_contract.json")):
            with self.subTest(app=str(contract_path.parent.relative_to(REPO_ROOT))):
                parsed = parse_app_contract_file(contract_path.parent)
                provided = [item.interface for item in parsed.contract.provides]
                required_aliases = [item.alias for item in parsed.contract.requires]
                self.assertEqual(len(provided), len(set(provided)))
                self.assertEqual(len(required_aliases), len(set(required_aliases)))
