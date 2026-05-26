from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

from core.apps.contracts import parse_app_contract_file
from core.shared.entrypoints import run_json_entrypoint

class CalendarContractTest(unittest.TestCase):
    def test_contract_parses(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        parsed = parse_app_contract_file(app_root)

        self.assertEqual(parsed.app_id, "calendar")
        self.assertEqual(parsed.contract.presentation.frontend_role, "workspace")
        self.assertEqual(parsed.contract.entrypoints.backend, "backend/app_backend.py")
        self.assertEqual(parsed.contract.storage.data_schema_version, "2")
        self.assertEqual(parsed.contract.capabilities.views, ["calendar"])
        self.assertIn("calendar_operations_manifest", parsed.contract.capabilities.mcp_tools)
        self.assertIn("calendar_check_availability", parsed.contract.capabilities.mcp_tools)
        self.assertIn("calendar_find_free_time", parsed.contract.capabilities.mcp_tools)
        self.assertIn("calendar_view_filter", parsed.contract.capabilities.mcp_tools)
        self.assertIn("calendar_reference_search", parsed.contract.capabilities.mcp_tools)
        self.assertEqual(parsed.contract.capabilities.cli_commands, ["calendar", "calendar-reference"])
        self.assertEqual(parsed.contract.entrypoints.mcp, "mcp/server.py")
        self.assertEqual(parsed.contract.entrypoints.cli, "cli/app_cli.py")
        self.assertEqual(parsed.contract.entrypoints.skills_root, "skills")
        self.assertEqual(parsed.contract.capabilities.skills, ["calendar-ops"])
        self.assertEqual(parsed.contract.capabilities.reference_entities[0].entity_type, "event")
        self.assertTrue(parsed.contract.capabilities.reference_entities[0].deep_link_supported)
        self.assertEqual(parsed.contract.capabilities.view_surfaces[0].entity_types, ["event"])

    def test_calendar_ops_skill_is_declared_and_discoverable(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        repo_root = app_root.parents[1]
        skill_path = app_root / "skills" / "calendar-ops" / "SKILL.md"
        content = skill_path.read_text(encoding="utf-8")

        self.assertTrue(skill_path.is_file())
        self.assertIn("name: calendar-ops", content)
        self.assertIn("maverick apps list --json", content)
        self.assertIn("maverick app <calendar_app_id> mcp list --json", content)
        self.assertIn("maverick app <calendar_app_id> cli list --json", content)
        self.assertIn("Do not read or write `data/calendar/state.json` directly.", content)
        self.assertIn("calendar_find_free_time", content)
        self.assertIn("conflict_policy", content)
        self.assertIn("iso 8601 timestamps", content.casefold())
        self.assertIn("timezone", content.casefold())
        self.assertIn("confirmation", content.casefold())

        skills_backend = repo_root / "apps" / "skills" / "backend"
        original_sys_path = list(sys.path)
        previous_modules = {name: sys.modules.get(name) for name in ("models", "seeds", "store")}
        try:
            sys.path.insert(0, str(skills_backend))
            from seeds import seed_default_skills, source_skill_roots
            from store import list_skills

            discovered = [path.name for path in source_skill_roots(repo_root)]
            with tempfile.TemporaryDirectory() as temp_dir:
                skills_data_root = Path(temp_dir) / "skills"
                seeded = seed_default_skills(skills_data_root, repository_root=repo_root)
                catalog_ids = [item["id"] for item in list_skills(skills_data_root)]
        finally:
            sys.path[:] = original_sys_path
            for module_name, previous_module in previous_modules.items():
                if previous_module is None:
                    sys.modules.pop(module_name, None)
                else:
                    sys.modules[module_name] = previous_module

        self.assertIn("calendar-ops", discovered)
        self.assertIn("calendar-ops", seeded)
        self.assertIn("calendar-ops", catalog_ids)

    def test_agent_surface_discovery_descriptors_and_manifest_invocation_are_aligned(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        parsed = parse_app_contract_file(app_root)
        tool_schemas = json.loads((app_root / "mcp" / "tool_schemas.json").read_text(encoding="utf-8"))
        command_schemas = json.loads((app_root / "cli" / "command_schemas.json").read_text(encoding="utf-8"))

        self.assertEqual(sorted(tool_schemas["tools"]), sorted(parsed.contract.capabilities.mcp_tools))
        self.assertEqual(sorted(command_schemas["commands"]), sorted(parsed.contract.capabilities.cli_commands))

        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            mcp_manifest = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_operations_manifest",
                    "arguments": {},
                },
            )
            cli_manifest = run_json_entrypoint(
                app_root / "cli" / "app_cli.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "command_id": "app.calendar.calendar",
                    "arguments": {},
                },
            )
            reference_manifest = run_json_entrypoint(
                app_root / "cli" / "app_cli.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "command_id": "app.calendar.calendar-reference",
                    "arguments": {},
                },
            )
            manifest_created_state = (data_root / "state.json").exists()

        self.assertEqual(mcp_manifest["status_code"], 200)
        self.assertEqual(cli_manifest["status_code"], 200)
        self.assertEqual(reference_manifest["status_code"], 200)
        self.assertFalse(manifest_created_state)
        self.assertEqual(mcp_manifest["action"], "operations.manifest")
        self.assertEqual(cli_manifest["action"], "operations.manifest")
        self.assertEqual(reference_manifest["action"], "references.manifest")
        self.assertEqual(
            sorted(tool["name"] for tool in mcp_manifest["tools"]),
            sorted(parsed.contract.capabilities.mcp_tools),
        )
        self.assertEqual(
            sorted(command["name"] for command in cli_manifest["commands"]),
            sorted(parsed.contract.capabilities.cli_commands),
        )
