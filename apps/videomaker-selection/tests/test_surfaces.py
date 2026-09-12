"""Static checks for the full Maverick app surface bundle."""
from __future__ import annotations
import json
from pathlib import Path
import unittest

APP_ROOT = Path(__file__).resolve().parents[1]


class SurfaceBundleTest(unittest.TestCase):
    def test_declared_entrypoints_exist(self) -> None:
        contract = json.loads((APP_ROOT / "app_contract.json").read_text())
        entrypoints = contract["entrypoints"]
        paths = [entrypoints["backend"], entrypoints["mcp"], entrypoints["cli"], *entrypoints["hooks"].values()]
        for relative in paths:
            self.assertTrue((APP_ROOT / relative).is_file(), relative)
        self.assertTrue((APP_ROOT / entrypoints["frontend"] / "index.html").is_file())

    def test_every_declared_widget_and_tool_has_an_artifact(self) -> None:
        contract = json.loads((APP_ROOT / "app_contract.json").read_text())
        for widget in contract["widgets"]:
            self.assertTrue((APP_ROOT / widget["frontend"]["mount"] / "index.html").is_file())
        tools = json.loads((APP_ROOT / "mcp" / "tool_schemas.json").read_text())["tools"]
        self.assertEqual(set(contract["capabilities"]["mcp_tools"]), set(tools))
        commands = json.loads((APP_ROOT / "cli" / "command_schemas.json").read_text())["commands"]
        self.assertEqual(set(contract["capabilities"]["cli_commands"]), set(commands))

    def test_app_is_self_contained_and_has_no_uninstall_hook(self) -> None:
        contract = json.loads((APP_ROOT / "app_contract.json").read_text())
        self.assertEqual(contract["requires"], [])
        self.assertEqual(contract["permissions"]["network"]["outbound"], [])
        self.assertFalse(contract["lifecycle"]["uninstall"])
        self.assertNotIn("uninstall", contract["entrypoints"]["hooks"])
        self.assertEqual(contract["storage"]["primary_paths"], ["data/videomaker-selection/app.db"])


if __name__ == "__main__":
    unittest.main()
