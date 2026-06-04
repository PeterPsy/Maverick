"""Generated contract smoke test."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

APP_ROOT = Path(__file__).resolve().parents[1]
MAVERICK_ROOT = APP_ROOT.parents[3]
sys.path.insert(0, str(MAVERICK_ROOT))

from core.apps.contracts import parse_app_contract_file


class GeneratedAppContractTest(unittest.TestCase):
    def test_contract_parses(self) -> None:
        parsed = parse_app_contract_file(APP_ROOT)
        self.assertEqual(parsed.app_id, "website-studio")

    def test_contract_declares_storage_write_requirement(self) -> None:
        contract = json.loads((APP_ROOT / "app_contract.json").read_text(encoding="utf-8"))
        requirements = contract.get("requires", [])
        self.assertIn("file.content.write", {item.get("interface") for item in requirements})

    def test_contract_declares_github_token_secret_logical_name(self) -> None:
        contract = json.loads((APP_ROOT / "app_contract.json").read_text(encoding="utf-8"))
        secret_reads = set(contract.get("permissions", {}).get("secrets", {}).get("read", []))
        self.assertIn("github-token", secret_reads)
        self.assertNotIn("github-app-private-key", secret_reads)

    def test_contract_declares_git_connection_setup_tools(self) -> None:
        contract = json.loads((APP_ROOT / "app_contract.json").read_text(encoding="utf-8"))
        mcp_tools = set(contract.get("capabilities", {}).get("mcp_tools", []))
        self.assertIn("website_git_connections_list", mcp_tools)
        self.assertIn("website_git_connection_prepare", mcp_tools)
        self.assertIn("website_git_connection_activate", mcp_tools)

        schemas = json.loads((APP_ROOT / "mcp" / "tool_schemas.json").read_text(encoding="utf-8"))
        self.assertIn("website_git_connection_prepare", schemas["tools"])
        self.assertIn("website_git_connection_activate", schemas["tools"])

    def test_phase2_tools_are_declared_when_implemented(self) -> None:
        contract = json.loads((APP_ROOT / "app_contract.json").read_text(encoding="utf-8"))
        mcp_tools = set(contract.get("capabilities", {}).get("mcp_tools", []))
        for tool in {
            "website_environment_configure",
            "website_build_validate",
            "website_approval_record",
            "website_publish",
            "website_rollback",
        }:
            self.assertIn(tool, mcp_tools)

        schemas = json.loads((APP_ROOT / "mcp" / "tool_schemas.json").read_text(encoding="utf-8"))
        self.assertIn("website_publish", schemas["tools"])
        self.assertIn("website_rollback", schemas["tools"])


if __name__ == "__main__":
    unittest.main()
