"""Generated contract smoke test."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

for parent in Path(__file__).resolve().parents:
    if (parent / "core").is_dir():
        sys.path.insert(0, str(parent))
        break

from core.apps.contracts import parse_app_contract_file

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from domains.action_catalog import CONFIG_HELPER_ACTIONS, MCP_TOOL_ACTIONS, UI_HELPER_ACTIONS


class GeneratedAppContractTest(unittest.TestCase):
    def test_contract_parses(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        parsed = parse_app_contract_file(app_root)
        self.assertEqual(parsed.app_id, "crm")
        self.assertEqual([widget.widget_id for widget in parsed.contract.widgets], ["crm-sidebar"])

    def test_mcp_surface_is_agent_facing_subset(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        parsed = parse_app_contract_file(app_root)
        declared = set(parsed.contract.capabilities.mcp_tools)
        descriptors = set(json.loads((app_root / "mcp" / "tool_schemas.json").read_text())["tools"])
        self.assertEqual(declared, set(MCP_TOOL_ACTIONS))
        self.assertEqual(descriptors, declared)
        self.assertEqual(len(declared), 59)

        helper_tools = {action.replace("crm.", "crm_") for action in UI_HELPER_ACTIONS + CONFIG_HELPER_ACTIONS}
        self.assertFalse(declared & helper_tools)


if __name__ == "__main__":
    unittest.main()
