"""Generated contract smoke test."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

MAVERICK_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / "core").is_dir())
sys.path.insert(0, str(MAVERICK_ROOT))

from core.apps.contracts import parse_app_contract_file
from core.apps.surface_descriptors import app_cli_command_secret_selectors, app_mcp_tool_secret_selectors
from apps.mail.backend import database


class GeneratedAppContractTest(unittest.TestCase):
    def test_contract_parses(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        parsed = parse_app_contract_file(app_root)
        self.assertEqual(parsed.app_id, "mail")

    def test_contract_storage_schema_version_matches_database_schema(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        parsed = parse_app_contract_file(app_root)

        self.assertEqual(parsed.contract.storage.data_schema_version, database.SCHEMA_VERSION)

    def test_sidebar_footer_widget_is_declared(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        contract = json.loads((app_root / "app_contract.json").read_text())
        widgets = {item["widget_id"]: item for item in contract["widgets"]}

        self.assertEqual(widgets["mail-sidebar"]["content_kinds"], ["shell.sidebar.primary"])
        self.assertEqual(widgets["mail-sidebar-footer"]["content_kinds"], ["shell.sidebar.footer"])
        self.assertEqual(
            widgets["mail-sidebar-footer"]["frontend"]["mount"],
            "frontend/dist/widgets/mail-sidebar-footer",
        )

    def test_gmail_oauth_secret_contract_matches_vault_acceptance_flow(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        parsed = parse_app_contract_file(app_root)
        secrets = parsed.contract.permissions.secrets

        self.assertEqual(
            secrets.read,
            [
                "gmail-oauth-client-id",
                "gmail-oauth-client-secret",
                "gmail-refresh-token",
                "mailbox-password",
            ],
        )
        self.assertEqual(secrets.write, ["gmail-refresh-token"])

        cli_selectors = app_cli_command_secret_selectors(
            app_root,
            "mail",
            declared_secret_names=secrets.read,
        )
        self.assertTrue(
            any(
                selector.logical_names == ["gmail-oauth-client-id"]
                and selector.when == {"action": "connections.start_oauth"}
                and selector.resource_type is None
                for selector in cli_selectors
            )
        )
        self.assertTrue(
            any(
                selector.logical_names == ["gmail-refresh-token"]
                and selector.resource_type == "mail_connection"
                for selector in cli_selectors
            )
        )
        self.assertTrue(
            any(
                selector.logical_names == ["mailbox-password"]
                and selector.resource_type == "mail_connection"
                and selector.resource_lookup == {"kind": "mail_connection_from_arguments"}
                for selector in cli_selectors
            )
        )

        mcp_selectors = app_mcp_tool_secret_selectors(
            app_root,
            "mail_sync",
            declared_secret_names=secrets.read,
        )
        self.assertTrue(
            any(
                selector.logical_names == ["gmail-oauth-client-id", "gmail-oauth-client-secret"]
                and selector.resource_type is None
                for selector in mcp_selectors
            )
        )
        self.assertTrue(
            any(
                selector.logical_names == ["gmail-refresh-token"]
                and selector.resource_type == "mail_connection"
                for selector in mcp_selectors
            )
        )
        self.assertTrue(
            any(
                selector.logical_names == ["mailbox-password"]
                and selector.resource_type == "mail_connection"
                for selector in mcp_selectors
            )
        )


if __name__ == "__main__":
    unittest.main()
