"""Tests for app reference tool manifests."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from core.apps.contracts import parse_app_contract_file
from core.shared.entrypoints import run_json_entrypoint


REPO_ROOT = Path(__file__).resolve().parents[1]


class ReferenceToolsContractTestCase(unittest.TestCase):
    def test_existing_app_contracts_parse_reference_entities(self) -> None:
        expected = {
            "agents": {"agent_type", "role_prompt"},
            "app-store": {"installed_app"},
            "base-shell": set(),
            "chat": {"thread", "project"},
            "dynamic-views": {"view"},
            "gallery": {"file"},
            "memory": {"node"},
            "skills": {"skill"},
            "user-admin": set(),
        }
        for app_id, entity_types in expected.items():
            with self.subTest(app_id=app_id):
                parsed = parse_app_contract_file(REPO_ROOT / "apps" / app_id)
                self.assertEqual({item.entity_type for item in parsed.contract.capabilities.reference_entities}, entity_types)

    def test_reference_manifest_entrypoints_return_common_shape(self) -> None:
        cases = [
            ("agents", "agents_reference_manifest", "agent_type"),
            ("gallery", "gallery_reference_manifest", "file"),
            ("skills", "skills_reference_manifest", "skill"),
            ("base-shell", "base_shell_reference_manifest", None),
            ("user-admin", "user_admin_reference_manifest", None),
        ]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for app_id, tool_name, expected_type in cases:
                with self.subTest(app_id=app_id):
                    app_root = REPO_ROOT / "apps" / app_id
                    result = run_json_entrypoint(
                        app_root / "mcp" / "server.py",
                        payload={
                            "workspace_id": "default",
                            "app_id": app_id,
                            "data_root": str(root / "data" / app_id),
                            "uploaded_storage_root": str(root / "storage" / "uploaded"),
                            "generated_storage_root": str(root / "storage" / "generated"),
                            "tool_name": tool_name,
                            "arguments": {},
                        },
                        cwd=app_root,
                    )
                    self.assertEqual(result["app_id"], app_id)
                    self.assertIn("entity_types", result)
                    if expected_type is not None:
                        self.assertIn(expected_type, {item["entity_type"] for item in result["entity_types"]})
                    else:
                        self.assertEqual(result["entity_types"], [])

    def test_reference_cli_entrypoints_return_common_shape(self) -> None:
        cases = [
            ("agents", "agent_type"),
            ("gallery", "file"),
            ("skills", "skill"),
            ("base-shell", None),
            ("user-admin", None),
        ]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for app_id, expected_type in cases:
                with self.subTest(app_id=app_id):
                    app_root = REPO_ROOT / "apps" / app_id
                    result = run_json_entrypoint(
                        app_root / "cli" / "app_cli.py",
                        payload={
                            "workspace_id": "default",
                            "app_id": app_id,
                            "data_root": str(root / "data" / app_id),
                            "uploaded_storage_root": str(root / "storage" / "uploaded"),
                            "generated_storage_root": str(root / "storage" / "generated"),
                            "command_id": f"app.{app_id}.{app_id}",
                            "arguments": {"action": "references.manifest"},
                        },
                        cwd=app_root,
                    )
                    self.assertEqual(result["app_id"], app_id)
                    self.assertIn("entity_types", result)
                    if expected_type is not None:
                        self.assertIn(expected_type, {item["entity_type"] for item in result["entity_types"]})
                    else:
                        self.assertEqual(result["entity_types"], [])
