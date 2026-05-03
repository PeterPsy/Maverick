from __future__ import annotations

import json
from pathlib import Path
import unittest


APP_ROOT = Path(__file__).resolve().parents[1]


class AgentsContractTest(unittest.TestCase):
    def test_contract_declares_agents_view_and_no_fleet_surface(self) -> None:
        contract = json.loads((APP_ROOT / "app_contract.json").read_text(encoding="utf-8"))

        views = set(contract["capabilities"]["views"])
        self.assertIn("agents", views)
        self.assertNotIn("fleet", views)

        primary_paths = set(contract["storage"]["primary_paths"])
        self.assertIn("data/agents/common_prompt.md", primary_paths)
        self.assertIn("data/agents/roles", primary_paths)
        self.assertIn("data/agents/agent_types.json", primary_paths)
        self.assertNotIn("data/agents/fleet_workflows.json", primary_paths)
        self.assertNotIn("data/agents/fleet_runs.json", primary_paths)

        surface_ids = {surface["view_id"] for surface in contract["capabilities"]["view_surfaces"]}
        self.assertEqual({"agents"}, surface_ids)

        widgets = {widget["widget_id"]: widget for widget in contract["widgets"]}
        self.assertEqual({"agents-sidebar", "agents-sidebar-footer"}, set(widgets))
        self.assertEqual("base-shell", widgets["agents-sidebar"]["host"])
        self.assertEqual(["shell.sidebar.primary"], widgets["agents-sidebar"]["content_kinds"])
        self.assertEqual("frontend/dist/widgets/agents-sidebar", widgets["agents-sidebar"]["frontend"]["mount"])
        self.assertEqual("base-shell", widgets["agents-sidebar-footer"]["host"])
        self.assertEqual(["shell.sidebar.footer"], widgets["agents-sidebar-footer"]["content_kinds"])
        self.assertEqual("frontend/dist/widgets/agents-sidebar-footer", widgets["agents-sidebar-footer"]["frontend"]["mount"])

        event_resources = {event["resource"] for event in contract["capabilities"]["data_events"]}
        self.assertIn("configuration", event_resources)
        self.assertIn("view-state", event_resources)
        self.assertNotIn("fleet", event_resources)


if __name__ == "__main__":
    unittest.main()
