"""Contract tests for Senses Phase 0."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

MAVERICK_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / "core").is_dir())
APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MAVERICK_ROOT))

from core.app_sdk.service import validate_app_source
from core.apps.contracts import parse_app_contract_file


class SensesContractTest(unittest.TestCase):
    def test_contract_declares_only_phase_0_surfaces(self) -> None:
        parsed = parse_app_contract_file(APP_ROOT)
        self.assertEqual(parsed.app_id, "senses")
        self.assertIsNone(parsed.contract.entrypoints.frontend)
        self.assertEqual(parsed.contract.entrypoints.backend, "backend/app_backend.py")
        self.assertEqual(parsed.contract.capabilities.cli_commands, ["senses"])
        self.assertEqual(
            parsed.contract.capabilities.mcp_tools,
            ["senses_reference_manifest", "senses_operations_manifest"],
        )
        self.assertEqual(parsed.contract.capabilities.views, [])
        self.assertEqual(parsed.contract.capabilities.reference_entities, [])
        self.assertEqual(parsed.contract.storage.primary_paths, ["data/senses/senses.sqlite"])

    def test_contract_declares_phase_0_storage_dependencies(self) -> None:
        parsed = parse_app_contract_file(APP_ROOT)
        requirements = {item.alias: item for item in parsed.contract.requires}
        self.assertEqual(requirements["storage-file-content-write"].interface, "file.content.write")
        self.assertEqual(requirements["storage-file-catalog"].interface, "file.catalog")
        self.assertTrue(requirements["storage-file-content-write"].required)
        self.assertTrue(requirements["storage-file-catalog"].required)

    def test_sdk_validation_passes(self) -> None:
        validation = validate_app_source(APP_ROOT)
        self.assertTrue(validation.valid, [issue.message for issue in validation.issues])


if __name__ == "__main__":
    unittest.main()
