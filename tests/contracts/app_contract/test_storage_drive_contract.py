"""Storage Google Drive contract and descriptor checks."""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from core.apps.contracts import parse_app_contract_file
from core.apps.surface_descriptors import (
    app_cli_command_secret_selectors,
    app_mcp_tool_secret_selectors,
    app_secret_requests_for_arguments,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
STORAGE_ROOT = REPO_ROOT / "apps" / "storage"


class StorageDriveContractTest(unittest.TestCase):
    def test_storage_declares_drive_permissions_and_agent_tools(self) -> None:
        parsed = parse_app_contract_file(STORAGE_ROOT)
        contract = parsed.contract

        self.assertEqual(
            contract.permissions.secrets.read,
            [
                "google-drive-oauth-client-id",
                "google-drive-oauth-client-secret",
                "google-drive-refresh-token",
            ],
        )
        self.assertEqual(contract.permissions.secrets.write, ["google-drive-refresh-token"])
        self.assertEqual(
            contract.permissions.network.outbound,
            ["accounts.google.com", "oauth2.googleapis.com", "www.googleapis.com"],
        )

        provided_interfaces = {item.interface for item in contract.provides}
        self.assertIn("file.provider.google-drive", provided_interfaces)
        drive_tools = {tool for tool in contract.capabilities.mcp_tools if tool.startswith("storage_drive_")}
        self.assertTrue(
            {
                "storage_drive_search",
                "storage_drive_read",
                "storage_drive_preview",
                "storage_drive_export",
                "storage_drive_index",
                "storage_drive_write",
                "storage_drive_move",
                "storage_drive_trash",
            }.issubset(drive_tools)
        )

    def test_drive_cli_selectors_scope_refresh_token_to_connection_resource(self) -> None:
        parsed = parse_app_contract_file(STORAGE_ROOT)
        selectors = app_cli_command_secret_selectors(
            STORAGE_ROOT,
            "storage",
            declared_secret_names=parsed.contract.permissions.secrets.read,
        )

        start_oauth = [
            selector
            for selector in selectors
            if selector.when == {"action": "drive_connections.start_oauth"}
        ]
        self.assertEqual(len(start_oauth), 1)
        self.assertEqual(start_oauth[0].logical_names, ["google-drive-oauth-client-id", "google-drive-oauth-client-secret"])
        self.assertIsNone(start_oauth[0].resource_type)

        requests = app_secret_requests_for_arguments(
            selectors,
            {"action": "drive_export", "connection_id": "drive_conn_1", "drive_file_id": "drive_file_1"},
        )
        request_scopes = {
            (tuple(request.logical_names), request.resource_type, request.resource_id)
            for request in requests
        }
        self.assertIn(
            (("google-drive-oauth-client-id", "google-drive-oauth-client-secret"), None, None),
            request_scopes,
        )
        self.assertIn(
            (("google-drive-refresh-token",), "drive_connection", "drive_conn_1"),
            request_scopes,
        )

    def test_drive_oauth_completion_is_backend_only(self) -> None:
        parsed = parse_app_contract_file(STORAGE_ROOT)
        self.assertNotIn("storage_drive_connections_complete_oauth", parsed.contract.capabilities.mcp_tools)

        cli_schemas = json.loads((STORAGE_ROOT / "cli" / "command_schemas.json").read_text(encoding="utf-8"))
        action_enum = cli_schemas["commands"]["storage"]["argument_schema"]["properties"]["action"]["enum"]
        self.assertNotIn("drive_connections.complete_oauth", action_enum)
        self.assertFalse(
            any(
                selector.get("when") == {"action": "drive_connections.complete_oauth"}
                for selector in cli_schemas["commands"]["storage"].get("secret_selectors", [])
            )
        )

        mcp_schemas = json.loads((STORAGE_ROOT / "mcp" / "tool_schemas.json").read_text(encoding="utf-8"))
        self.assertNotIn("storage_drive_connections_complete_oauth", mcp_schemas["tools"])
        generic_action_enum = mcp_schemas["tools"]["maverick_storage"]["input_schema"]["properties"]["action"]["enum"]
        self.assertNotIn("drive_connections.complete_oauth", generic_action_enum)

    def test_drive_mcp_selectors_and_schemas_keep_remote_identity_explicit(self) -> None:
        parsed = parse_app_contract_file(STORAGE_ROOT)
        selectors = app_mcp_tool_secret_selectors(
            STORAGE_ROOT,
            "storage_drive_export",
            declared_secret_names=parsed.contract.permissions.secrets.read,
        )
        self.assertTrue(
            any(
                selector.logical_names == ["google-drive-refresh-token"]
                and selector.resource_type == "drive_connection"
                and selector.resource_id_argument == "connection_id"
                for selector in selectors
            )
        )

        schemas = json.loads((STORAGE_ROOT / "mcp" / "tool_schemas.json").read_text(encoding="utf-8"))
        for tool_name in ("storage_drive_search", "storage_drive_export", "storage_drive_index", "storage_drive_write"):
            with self.subTest(tool=tool_name):
                properties = schemas["tools"][tool_name]["input_schema"]["properties"]
                self.assertIn("connection_id", properties)
                self.assertNotIn("workspace_relative_path", properties)

    def test_storage_skill_documents_drive_to_memory_workflow(self) -> None:
        skill = (STORAGE_ROOT / "skills" / "storage-ops" / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("Google Drive Agent Workflow", skill)
        self.assertIn("storage_drive_index", skill)
        self.assertIn("memory_ingest_storage_source", skill)
        self.assertIn("storage_drive_mark_indexed", skill)
        self.assertIn("memory_apply_storage_staleness", skill)

    def test_drive_mcp_write_tools_can_resolve_refresh_token_from_stable_storage_file_id(self) -> None:
        parsed = parse_app_contract_file(STORAGE_ROOT)

        for tool_name in ("storage_drive_write", "storage_drive_rename", "storage_drive_move", "storage_drive_trash"):
            with self.subTest(tool=tool_name):
                selectors = app_mcp_tool_secret_selectors(
                    STORAGE_ROOT,
                    tool_name,
                    declared_secret_names=parsed.contract.permissions.secrets.read,
                )
                self.assertTrue(
                    any(
                        selector.logical_names == ["google-drive-refresh-token"]
                        and selector.resource_type == "drive_connection"
                        and selector.resource_lookup == {"kind": "storage_drive_file"}
                        for selector in selectors
                    )
                )
                requests = app_secret_requests_for_arguments(
                    selectors,
                    {"stable_storage_file_id": "file_stable_abc"},
                    resource_lookup=lambda selector: {
                        "requires_secrets": True,
                        "resource_type": "drive_connection",
                        "resource_id": "drive_conn_abc",
                    }
                    if selector.resource_lookup
                    else None,
                )
                self.assertIn(
                    (("google-drive-refresh-token",), "drive_connection", "drive_conn_abc"),
                    {
                        (tuple(request.logical_names), request.resource_type, request.resource_id)
                        for request in requests
                    },
                )


if __name__ == "__main__":
    unittest.main()
