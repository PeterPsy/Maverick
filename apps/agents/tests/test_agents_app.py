"""Tests for the simplified Agents app."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

from core.apps.contracts import parse_app_contract_file


APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT / "backend"))

from seeds import seed_defaults
from service import app_events_for_action, app_events_for_result, handle_action
from store import list_agent_definitions


class AgentsAppTestCase(unittest.TestCase):
    def test_contract_exposes_one_agent_catalog_shape(self) -> None:
        parsed = parse_app_contract_file(APP_ROOT)

        self.assertEqual(parsed.app_id, "agents")
        self.assertEqual([item.interface for item in parsed.contract.provides], ["agent.catalog"])
        self.assertEqual(
            [item.entity_type for item in parsed.contract.capabilities.reference_entities],
            ["agent_type"],
        )
        self.assertIn(
            "agents_delete_agent_definition",
            parsed.contract.capabilities.mcp_tools,
        )
        self.assertEqual(parsed.contract.capabilities.skills, ["agents-ops"])

    def test_new_catalog_is_empty_and_uses_one_json_store(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "agents"
            result = seed_defaults(data_root)

            self.assertEqual(result, {"agent_count": 0})
            self.assertEqual(list_agent_definitions(data_root), [])
            self.assertTrue((data_root / "agents.json").is_file())
            self.assertFalse((data_root / "roles").exists())
            self.assertFalse((data_root / "common_prompt.md").exists())
            self.assertFalse((data_root / "agent_types.json").exists())

    def test_upsert_get_and_delete_use_one_self_contained_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "agents"
            status, created = handle_action(data_root, {
                "action": "upsert_agent_definition",
                "id": "example",
                "name": "Example",
                "description": "One focused agent.",
                "instructions": "Do the focused work.",
                "skill_ids": ["prompt-library", "prompt-library"],
            })
            get_status, loaded = handle_action(data_root, {
                "action": "get_agent_definition",
                "id": "agent-type-example",
            })
            delete_status, deleted = handle_action(data_root, {
                "action": "delete_agent_definition",
                "id": "agent-type-example",
            })

            self.assertEqual((status, get_status, delete_status), (200, 200, 200))
            self.assertTrue(created["created"])
            self.assertEqual(created["agent_definition"]["skill_ids"], ["prompt-library"])
            self.assertEqual(loaded["agent_definition"]["instructions"], "Do the focused work.")
            self.assertTrue(deleted["deleted"])
            document = json.loads((data_root / "agents.json").read_text(encoding="utf-8"))
            self.assertEqual(document, {"schema_version": "2", "agents": []})

    def test_compact_catalog_omits_instructions(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "agents"
            handle_action(data_root, {
                "action": "upsert_agent_definition",
                "id": "agent-type-example",
                "name": "Example",
                "instructions": "Private instructions.",
            })
            _status, compact = handle_action(data_root, {
                "action": "catalog.compact",
            })
            _status, full = handle_action(data_root, {"action": "catalog"})

            self.assertNotIn("instructions", compact["agent_types"][0])
            self.assertEqual(full["agent_types"][0]["instructions"], "Private instructions.")
            self.assertEqual(compact["count"], 1)

    def test_idempotent_upsert_emits_no_change_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "agents"
            body = {
                "action": "upsert_agent_definition",
                "id": "agent-type-example",
                "name": "Example",
                "instructions": "Focused.",
            }
            handle_action(data_root, body)
            _status, result = handle_action(data_root, body)

            self.assertFalse(result["created"])
            self.assertFalse(result["changed"])
            self.assertEqual(app_events_for_result(body["action"], result), [])

    def test_obsolete_role_prompt_and_preview_actions_are_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "agents"
            for action in (
                "list_roles",
                "create_role",
                "create_agent_type",
                "set_common_prompt",
                "preview_prompt",
                "agent.prompt.preview",
            ):
                status, payload = handle_action(data_root, {"action": action})
                self.assertEqual(status, 400)
                self.assertEqual(payload["error"], "unsupported_action")

    def test_view_and_references_accept_agents_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "agents"
            status, custom = handle_action(data_root, {
                "action": "set_custom_view",
                "refs": [{"entity_type": "agent_type", "entity_id": "agent-type-example"}],
            })
            self.assertEqual(status, 200)
            self.assertEqual(custom["state"]["view_filter"]["mode"], "custom")
            with self.assertRaisesRegex(ValueError, "agent_type"):
                handle_action(data_root, {
                    "action": "set_custom_view",
                    "refs": [{"entity_type": "role_prompt", "entity_id": "role"}],
                })

    def test_frontend_contains_only_agent_instructions_and_explicit_skills(self) -> None:
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                APP_ROOT / "frontend" / "src" / "App.tsx",
                APP_ROOT / "frontend" / "src" / "components" / "AgentsDetail.tsx",
                APP_ROOT / "frontend" / "src" / "types.ts",
            )
        )
        for obsolete in (
            "Common Prompt",
            "Prompt Preview",
            "TraceMeter",
            "skillActivationMode",
            "selectedRole",
            "role_id",
            "trace_verbosity",
        ):
            self.assertNotIn(obsolete, source)
        self.assertIn("Explicit Skills", source)
        self.assertIn("instructions", source)

    def test_data_and_view_actions_emit_separate_events(self) -> None:
        self.assertEqual(
            app_events_for_action("upsert_agent_definition"),
            [{"type": "maverick.app.data-changed", "resource": "configuration"}],
        )
        self.assertEqual(
            app_events_for_action("set_view_filter"),
            [{"type": "maverick.app.data-changed", "resource": "view-state"}],
        )
        self.assertEqual(app_events_for_action("catalog"), [])


if __name__ == "__main__":
    unittest.main()
