"""Static checks for the full Maverick app surface bundle."""
from __future__ import annotations
import json
from pathlib import Path
import struct
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

    def test_compact_icon_is_app_owned_and_published(self) -> None:
        source = APP_ROOT / "frontend" / "public" / "maverick-icon-compact.png"
        published = APP_ROOT / "frontend" / "dist" / "maverick-icon-compact.png"

        self.assertTrue(source.is_file())
        self.assertTrue(published.is_file())
        image = source.read_bytes()
        self.assertEqual(published.read_bytes(), image)
        self.assertEqual(image[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", image[16:24]), (512, 512))
        self.assertEqual(image[25], 6, "The compact icon must be a transparent RGBA PNG")


if __name__ == "__main__":
    unittest.main()
