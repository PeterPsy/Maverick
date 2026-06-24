"""Contract tests for Senses Phase 7."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

MAVERICK_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / "core").is_dir())
APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MAVERICK_ROOT))

from core.app_sdk.service import validate_app_source
from core.apps.contracts import parse_app_contract_file


class SensesContractTest(unittest.TestCase):
    def test_contract_declares_phase_7_surfaces(self) -> None:
        parsed = parse_app_contract_file(APP_ROOT)
        self.assertEqual(parsed.app_id, "senses")
        self.assertEqual(parsed.contract.entrypoints.frontend, "frontend/dist")
        self.assertEqual(parsed.contract.entrypoints.backend, "backend/app_backend.py")
        self.assertEqual(parsed.contract.capabilities.cli_commands, ["senses"])
        self.assertEqual(
            parsed.contract.capabilities.mcp_tools,
            [
                "senses_reference_manifest",
                "senses_operations_manifest",
                "senses_view_filter",
                "senses_set_view_filter",
                "senses_set_custom_view",
                "senses_clear_custom_view",
            ],
        )
        self.assertEqual(parsed.contract.capabilities.views, ["main"])
        self.assertEqual(parsed.contract.capabilities.reference_entities, [])
        self.assertEqual(parsed.contract.capabilities.view_surfaces[0].view_id, "main")
        self.assertEqual(parsed.contract.storage.primary_paths, ["data/senses/senses.sqlite"])

    def test_contract_declares_phase_7_storage_dependencies(self) -> None:
        parsed = parse_app_contract_file(APP_ROOT)
        requirements = {item.alias: item for item in parsed.contract.requires}
        self.assertEqual(requirements["storage-file-content-write"].interface, "file.content.write")
        self.assertEqual(requirements["storage-file-catalog"].interface, "file.catalog")
        self.assertEqual(requirements["chat-communication"].interface, "communication.chat")
        self.assertTrue(requirements["storage-file-content-write"].required)
        self.assertTrue(requirements["storage-file-catalog"].required)
        self.assertFalse(requirements["chat-communication"].required)

    def test_contract_declares_device_registry_interface_and_events(self) -> None:
        contract = json.loads((APP_ROOT / "app_contract.json").read_text(encoding="utf-8"))
        self.assertEqual(contract["version"], "0.7.0")
        self.assertEqual(contract["presentation"]["frontend_role"], "workspace")
        self.assertEqual(contract["storage"]["data_schema_version"], "4")
        self.assertTrue(contract["permissions"]["runtime"]["create_sessions"])
        provided = {item["interface"]: item for item in contract["provides"]}
        self.assertEqual(provided["device.registry"]["version"], "1")
        self.assertEqual(provided["device.registry"]["surfaces"], ["backend", "view", "widget"])
        event_resources = {item["resource"] for item in contract["capabilities"]["data_events"]}
        self.assertEqual(event_resources, {"devices", "pairing", "settings", "captures", "routing", "view-state"})

    def test_contract_declares_base_shell_sidebar_widget(self) -> None:
        parsed = parse_app_contract_file(APP_ROOT)
        widgets = {widget.widget_id: widget for widget in parsed.contract.widgets}
        sidebar_widget = widgets["senses-sidebar"]
        vite_source = (APP_ROOT / "vite.config.ts").read_text(encoding="utf-8")
        sidebar_source = (APP_ROOT / "frontend" / "src" / "widgets" / "senses-sidebar" / "main.tsx").read_text(encoding="utf-8")

        self.assertEqual(sidebar_widget.host, "base-shell")
        self.assertEqual(sidebar_widget.content_kinds, ["shell.sidebar.primary"])
        self.assertEqual(sidebar_widget.frontend.mount, "frontend/dist/widgets/senses-sidebar")
        self.assertIn("'widgets/senses-sidebar/index': 'frontend/widgets/senses-sidebar/index.html'", vite_source)
        self.assertIn("maverick.widget.open-app", sidebar_source)
        self.assertIn("maverick.shell.sidebar.close", sidebar_source)

    def test_sdk_validation_passes(self) -> None:
        validation = validate_app_source(APP_ROOT)
        self.assertTrue(validation.valid, [issue.message for issue in validation.issues])


if __name__ == "__main__":
    unittest.main()
