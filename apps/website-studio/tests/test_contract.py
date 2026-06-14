"""Generated contract smoke test."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

APP_ROOT = Path(__file__).resolve().parents[1]
MAVERICK_ROOT = next(parent for parent in APP_ROOT.parents if (parent / "core").is_dir())
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

    def test_contract_publisher_matches_source_available_platform_app(self) -> None:
        contract = json.loads((APP_ROOT / "app_contract.json").read_text(encoding="utf-8"))
        self.assertEqual(contract.get("publisher"), "maverick")
        self.assertEqual(contract.get("distribution", {}).get("mode"), "source_available")
        self.assertEqual(contract.get("distribution", {}).get("source_access"), "forkable")

    def test_contract_declares_github_token_secret_logical_name(self) -> None:
        contract = json.loads((APP_ROOT / "app_contract.json").read_text(encoding="utf-8"))
        secret_reads = set(contract.get("permissions", {}).get("secrets", {}).get("read", []))
        self.assertIn("github-token", secret_reads)
        self.assertNotIn("github-app-private-key", secret_reads)

    def test_contract_declares_runtime_build_network_hosts(self) -> None:
        contract = json.loads((APP_ROOT / "app_contract.json").read_text(encoding="utf-8"))
        outbound = set(contract.get("permissions", {}).get("network", {}).get("outbound", []))

        self.assertIn("github.com", outbound)
        self.assertIn("api.github.com", outbound)
        self.assertIn("registry.npmjs.org", outbound)

    def test_contract_declares_git_connection_setup_tools(self) -> None:
        contract = json.loads((APP_ROOT / "app_contract.json").read_text(encoding="utf-8"))
        mcp_tools = set(contract.get("capabilities", {}).get("mcp_tools", []))
        self.assertIn("website_git_connections_list", mcp_tools)
        self.assertIn("website_git_connection_prepare", mcp_tools)
        self.assertIn("website_git_connection_activate", mcp_tools)
        self.assertIn("website_sync_source", mcp_tools)

        schemas = json.loads((APP_ROOT / "mcp" / "tool_schemas.json").read_text(encoding="utf-8"))
        self.assertIn("website_git_connection_prepare", schemas["tools"])
        self.assertIn("website_git_connection_activate", schemas["tools"])
        self.assertIn("website_sync_source", schemas["tools"])

    def test_git_secret_consumers_are_declared_for_cli_and_mcp(self) -> None:
        mcp_schemas = json.loads((APP_ROOT / "mcp" / "tool_schemas.json").read_text(encoding="utf-8"))
        import_selectors = mcp_schemas["tools"]["website_import_git"].get("secret_selectors", [])
        publish_selectors = mcp_schemas["tools"]["website_publish"].get("secret_selectors", [])
        self.assertIn(
            {"required_secrets": ["github-token"], "resource_lookup": {"kind": "website_git_connection_from_arguments"}},
            import_selectors,
        )
        self.assertIn(
            {"required_secrets": ["github-token"], "resource_lookup": {"kind": "website_git_publish_from_arguments"}},
            publish_selectors,
        )

        cli_schemas = json.loads((APP_ROOT / "cli" / "command_schemas.json").read_text(encoding="utf-8"))
        cli_selectors = cli_schemas["commands"]["website-studio"].get("secret_selectors", [])
        self.assertIn(
            {
                "required_secrets": ["github-token"],
                "resource_lookup": {"kind": "website_git_connection_from_arguments"},
                "when": {"action": "import_git"},
            },
            cli_selectors,
        )
        self.assertIn(
            {
                "required_secrets": ["github-token"],
                "resource_lookup": {"kind": "website_git_connection_from_arguments"},
                "when": {"action": "sync_source"},
            },
            cli_selectors,
        )
        self.assertIn(
            {
                "required_secrets": ["github-token"],
                "resource_lookup": {"kind": "website_git_publish_from_arguments"},
                "when": {"action": "publish"},
            },
            cli_selectors,
        )

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

    def test_phase3_publish_target_tools_are_declared_when_implemented(self) -> None:
        contract = json.loads((APP_ROOT / "app_contract.json").read_text(encoding="utf-8"))
        mcp_tools = set(contract.get("capabilities", {}).get("mcp_tools", []))
        self.assertIn("website_publish_targets_list", mcp_tools)
        self.assertIn("website_publish_target_configure", mcp_tools)

        schemas = json.loads((APP_ROOT / "mcp" / "tool_schemas.json").read_text(encoding="utf-8"))
        self.assertIn("website_publish_targets_list", schemas["tools"])
        self.assertIn("website_publish_target_configure", schemas["tools"])

    def test_phase3a_runtime_preview_tools_are_declared_when_implemented(self) -> None:
        contract = json.loads((APP_ROOT / "app_contract.json").read_text(encoding="utf-8"))
        mcp_tools = set(contract.get("capabilities", {}).get("mcp_tools", []))
        self.assertIn("website_bootstrap", mcp_tools)
        self.assertIn("website_preview_document", mcp_tools)
        self.assertIn("website_preview_report", mcp_tools)
        self.assertIn("website_navigation_analyze", mcp_tools)
        self.assertIn("website_runtime_status", mcp_tools)

        schemas = json.loads((APP_ROOT / "mcp" / "tool_schemas.json").read_text(encoding="utf-8"))
        self.assertIn("website_bootstrap", schemas["tools"])
        self.assertIn("website_preview_document", schemas["tools"])
        self.assertIn("website_preview_report", schemas["tools"])
        self.assertIn("website_navigation_analyze", schemas["tools"])
        self.assertIn("website_runtime_status", schemas["tools"])
        self.assertIn("website_maintenance_prune", schemas["tools"])

        cli_schema = json.loads((APP_ROOT / "cli" / "command_schemas.json").read_text(encoding="utf-8"))
        actions = set(cli_schema["commands"]["website-studio"]["argument_schema"]["properties"]["action"]["enum"])
        self.assertIn("bootstrap", actions)
        self.assertIn("preview_document", actions)
        self.assertIn("preview_report", actions)
        self.assertIn("navigation_analyze", actions)
        self.assertIn("runtime_status", actions)
        self.assertIn("maintenance_prune", actions)


if __name__ == "__main__":
    unittest.main()
