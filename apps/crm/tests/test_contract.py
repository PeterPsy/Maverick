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
    def test_cli_effects_and_schema_keys_are_unambiguous(self) -> None:
        def unique_keys(pairs):
            result = {}
            for key, value in pairs:
                self.assertNotIn(key, result, f'Duplicate JSON key: {key}')
                result[key] = value
            return result
        root = Path(__file__).resolve().parents[1]
        schema = json.loads((root / 'cli/command_schemas.json').read_text(), object_pairs_hook=unique_keys)['commands']['crm']
        self.assertEqual(schema['effect_class'], 'destructive')
        self.assertEqual(schema['effect_class_by_argument']['argument_name'], 'subcommand')
        effects = schema['effect_class_by_argument']['value_effect_classes']
        self.assertEqual(effects['crm.import_plan'], 'read')
        self.assertEqual(effects['crm.import_apply'], 'mutating')
        self.assertEqual(effects['crm.delete_record'], 'destructive')
        properties = schema['argument_schema']['properties']
        self.assertEqual([item['type'] for item in properties['action']['oneOf']], ['string', 'object'])
        self.assertEqual([item['type'] for item in properties['source']['oneOf']], ['string', 'object'])

    def test_contract_parses(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        parsed = parse_app_contract_file(app_root)
        self.assertEqual(parsed.app_id, "crm")
        self.assertEqual([widget.widget_id for widget in parsed.contract.widgets], ["crm-sidebar"])
        requirements = {requirement.alias: requirement.interface for requirement in parsed.contract.requires}
        self.assertEqual(
            requirements,
            {
                "mail": "mail.workspace",
                "calendar": "calendar.events",
                "files": "file.catalog",
                "file-preview": "file.preview",
                "file-write": "file.content.write",
                "speech": "speech.transcription",
                "tasks": "checklist.task",
            },
        )
        self.assertTrue(all(not requirement.required for requirement in parsed.contract.requires))

    def test_mcp_surface_matches_declared_contract(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        parsed = parse_app_contract_file(app_root)
        declared = set(parsed.contract.capabilities.mcp_tools)
        descriptors = set(json.loads((app_root / "mcp" / "tool_schemas.json").read_text())["tools"])
        descriptor_payload = json.loads((app_root / "mcp" / "tool_schemas.json").read_text())["tools"]
        self.assertEqual(declared, set(MCP_TOOL_ACTIONS))
        self.assertEqual(descriptors, declared)
        self.assertEqual(len(declared), 77)
        self.assertEqual(
            set(descriptor_payload["crm_link_external_ref"]["input_schema"]["required"]),
            {"crm_entity_type", "crm_entity_id", "source_app_id", "source_entity_type", "source_entity_id"},
        )

        standard_view_tools = {"crm_view_filter", "crm_set_view_filter", "crm_set_custom_view", "crm_clear_custom_view"}
        helper_tools = {action.replace("crm.", "crm_") for action in UI_HELPER_ACTIONS + CONFIG_HELPER_ACTIONS} - standard_view_tools
        self.assertFalse(declared & helper_tools)

    def test_skill_requires_dependency_selection_before_external_links(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        skill = (app_root / "skills" / "crm-ops" / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("maverick core cli run app.crm.dependencies --json", skill)
        self.assertIn("selected_provider_app_ids", skill)
        self.assertIn("never a hardcoded default", skill)


if __name__ == "__main__":
    unittest.main()
