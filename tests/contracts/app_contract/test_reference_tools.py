"""Tests for app reference tool manifests."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from core.apps.contracts import parse_app_contract_file
from core.shared.entrypoints import run_json_entrypoint


REPO_ROOT = Path(__file__).resolve().parents[3]


class ReferenceToolsContractTestCase(unittest.TestCase):
    def test_existing_app_contracts_parse_reference_entities(self) -> None:
        for app_root in sorted((REPO_ROOT / "apps").glob("*/app_contract.json")):
            with self.subTest(app_id=app_root.parent.name):
                parsed = parse_app_contract_file(app_root.parent)
                self.assertIsInstance({item.entity_type for item in parsed.contract.capabilities.reference_entities}, set)

    def test_reference_manifest_entrypoints_return_common_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for app_root in sorted((REPO_ROOT / "apps").glob("*/app_contract.json")):
                parsed = parse_app_contract_file(app_root.parent)
                tool_name = next(
                    (tool for tool in parsed.contract.capabilities.mcp_tools if tool.endswith("_reference_manifest")),
                    None,
                )
                if tool_name is None or parsed.contract.entrypoints.mcp is None:
                    continue
                with self.subTest(app_id=parsed.app_id):
                    result = run_json_entrypoint(
                        app_root.parent / parsed.contract.entrypoints.mcp,
                        payload={
                            "workspace_id": "default",
                            "app_id": parsed.app_id,
                            "data_root": str(root / "data" / parsed.app_id),
                            "uploaded_storage_root": str(root / "storage" / "uploaded"),
                            "generated_storage_root": str(root / "storage" / "generated"),
                            "tool_name": tool_name,
                            "arguments": {},
                        },
                        cwd=app_root.parent,
                    )
                    self.assertEqual(result["app_id"], parsed.app_id)
                    entity_types = result.get("entity_types")
                    if entity_types is None and isinstance(result.get("reference_manifest"), dict):
                        entity_types = result["reference_manifest"].get("entity_types")
                    self.assertIsInstance(entity_types, list)

    def test_reference_cli_entrypoints_return_common_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for app_root in sorted((REPO_ROOT / "apps").glob("*/app_contract.json")):
                parsed = parse_app_contract_file(app_root.parent)
                if parsed.contract.entrypoints.cli is None:
                    continue
                if not any(tool.endswith("_reference_manifest") for tool in parsed.contract.capabilities.mcp_tools):
                    continue
                with self.subTest(app_id=parsed.app_id):
                    result = run_json_entrypoint(
                        app_root.parent / parsed.contract.entrypoints.cli,
                        payload={
                            "workspace_id": "default",
                            "app_id": parsed.app_id,
                            "data_root": str(root / "data" / parsed.app_id),
                            "uploaded_storage_root": str(root / "storage" / "uploaded"),
                            "generated_storage_root": str(root / "storage" / "generated"),
                            "command_id": f"app.{parsed.app_id}.{parsed.app_id}",
                            "arguments": {"action": "references.manifest"},
                        },
                        cwd=app_root.parent,
                    )
                    self.assertEqual(result["app_id"], parsed.app_id)
                    entity_types = result.get("entity_types")
                    if entity_types is None and isinstance(result.get("reference_manifest"), dict):
                        entity_types = result["reference_manifest"].get("entity_types")
                    if entity_types is None:
                        continue
                    self.assertIsInstance(entity_types, list)
