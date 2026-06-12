"""Generated contract smoke test."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

MAVERICK_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / "core").is_dir())
sys.path.insert(0, str(MAVERICK_ROOT))

from core.apps.contracts import parse_app_contract_file


class GeneratedAppContractTest(unittest.TestCase):
    def test_contract_parses(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        parsed = parse_app_contract_file(app_root)
        self.assertEqual(parsed.app_id, "fitness-coach")

    def test_contract_declares_only_v1_tools(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        parsed = parse_app_contract_file(app_root)
        tools = set(parsed.contract.capabilities.mcp_tools)
        self.assertIn("fitness_coach_create_workout", tools)
        self.assertIn("fitness_coach_list_runs", tools)
        self.assertNotIn("fitness_coach_create_workout_from_media_folder", tools)
        self.assertNotIn("fitness_coach_analyze_media", tools)
        self.assertEqual(parsed.contract.distribution.mode, "source_available")
        self.assertEqual(parsed.contract.distribution.source_access, "forkable")

    def test_contract_declares_storage_requires_and_widgets(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        parsed = parse_app_contract_file(app_root)
        required_interfaces = {item.interface for item in parsed.contract.requires}
        self.assertIn("file.catalog", required_interfaces)
        self.assertIn("file.preview", required_interfaces)
        self.assertIn("file.content.read", required_interfaces)
        self.assertIn("file.media.stream", required_interfaces)
        widget_ids = {widget.widget_id for widget in parsed.contract.widgets}
        self.assertEqual(widget_ids, {"fitness-coach-sidebar", "fitness-coach-sidebar-footer"})


if __name__ == "__main__":
    unittest.main()
