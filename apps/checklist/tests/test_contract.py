"""Generated contract smoke test."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from core.apps.contracts import parse_app_contract_file
from core.shared.entrypoints import run_json_entrypoint


class GeneratedAppContractTest(unittest.TestCase):
    def test_contract_parses(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        parsed = parse_app_contract_file(app_root)
        self.assertEqual(parsed.app_id, "checklist")
        self.assertEqual(parsed.contract.capabilities.cli_commands, ["checklist", "checklist-reference", "checklist-view"])
        self.assertIn("checklist_reference_search", parsed.contract.capabilities.mcp_tools)
        self.assertIn("checklist_set_custom_view", parsed.contract.capabilities.mcp_tools)
        self.assertEqual(parsed.contract.capabilities.reference_entities[0].entity_type, "checklist")
        surface = parsed.contract.capabilities.view_surfaces[0]
        self.assertEqual(surface.view_id, "main")
        self.assertEqual(surface.entity_types, ["checklist"])
        actions = {item.action: item for item in surface.state_actions}
        self.assertTrue(actions["set_custom_view"].standard)
        self.assertTrue(actions["set_view_filter"].standard)
        self.assertTrue(surface.supports_custom_view)
        self.assertEqual(parsed.contract.widgets[0].widget_id, "design-checklist")
        self.assertEqual(parsed.contract.widgets[0].host, "chat")
        self.assertEqual(parsed.contract.widgets[0].content_kinds, ["checklist.design"])

    def test_maverick_tasklist_creates_chat_render_payload(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            result = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "checklist",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "maverick_tasklist",
                    "arguments": {
                        "action": "create",
                        "payload": {
                            "title": "Agency launch",
                            "sections": [
                                {
                                    "id": "foundations",
                                    "title": "Foundations",
                                    "tasks": [{"id": "name", "title": "Define name", "checked": False}],
                                }
                            ],
                        },
                    },
                },
            )

        self.assertEqual(result["status_code"], 201)
        self.assertEqual(result["chat_render"]["kind"], "checklist.design")
        self.assertEqual(result["chat_render"]["legacy_kind"], "design_checklist")
        self.assertEqual(result["chat_render"]["payload"]["sections"][0]["tasks"][0]["title"], "Define name")

    def test_backend_updates_v2_style_sections(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            created = run_json_entrypoint(
                app_root / "backend" / "app_backend.py",
                cwd=app_root,
                payload={
                    "app_id": "checklist",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "body": {
                        "action": "create",
                        "payload": {
                            "title": "Board",
                            "sections": [
                                {
                                    "id": "main",
                                    "title": "Main",
                                    "tasks": [{"id": "task-1", "title": "Ship widget", "checked": False}],
                                }
                            ],
                        },
                    },
                },
            )
            checklist_id = created["json"]["checklist"]["id"]
            updated = run_json_entrypoint(
                app_root / "backend" / "app_backend.py",
                cwd=app_root,
                payload={
                    "app_id": "checklist",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "body": {
                        "action": "update",
                        "id": checklist_id,
                        "payload": {
                            "sections": [
                                {
                                    "id": "main",
                                    "title": "Main",
                                    "tasks": [{"id": "task-1", "title": "Ship widget", "checked": True}],
                                }
                            ]
                        },
                    },
                },
            )

        self.assertEqual(updated["status_code"], 200)
        self.assertEqual(updated["json"]["checklist"]["checked_count"], 1)

    def test_backend_preserves_empty_task_rows_on_update(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            created = run_json_entrypoint(
                app_root / "backend" / "app_backend.py",
                cwd=app_root,
                payload={
                    "app_id": "checklist",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "body": {
                        "action": "create",
                        "payload": {
                            "title": "Board",
                            "sections": [
                                {
                                    "id": "main",
                                    "title": "Main",
                                    "tasks": [{"id": "task-1", "title": "Filled", "checked": False}],
                                }
                            ],
                        },
                    },
                },
            )
            checklist_id = created["json"]["checklist"]["id"]
            updated = run_json_entrypoint(
                app_root / "backend" / "app_backend.py",
                cwd=app_root,
                payload={
                    "app_id": "checklist",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "body": {
                        "action": "update",
                        "id": checklist_id,
                        "payload": {
                            "sections": [
                                {
                                    "id": "main",
                                    "title": "Main",
                                    "tasks": [
                                        {"id": "task-1", "title": "Filled", "checked": False},
                                        {"id": "task-2", "title": "", "checked": False},
                                    ],
                                }
                            ]
                        },
                    },
                },
            )
            reread = run_json_entrypoint(
                app_root / "backend" / "app_backend.py",
                cwd=app_root,
                payload={
                    "app_id": "checklist",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "body": {"action": "read", "id": checklist_id},
                },
            )

        self.assertEqual(updated["status_code"], 200)
        self.assertEqual(len(updated["json"]["checklist"]["sections"][0]["tasks"]), 2)
        self.assertEqual(updated["json"]["checklist"]["sections"][0]["tasks"][1]["title"], "")
        self.assertEqual(reread["json"]["checklist"]["sections"][0]["tasks"][1]["title"], "")

    def test_list_order_stays_stable_after_editing_an_older_checklist(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            first = run_json_entrypoint(
                app_root / "backend" / "app_backend.py",
                cwd=app_root,
                payload={
                    "app_id": "checklist",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "body": {
                        "action": "create",
                        "payload": {"title": "Older", "sections": [{"id": "main", "title": "", "tasks": []}]},
                    },
                },
            )
            second = run_json_entrypoint(
                app_root / "backend" / "app_backend.py",
                cwd=app_root,
                payload={
                    "app_id": "checklist",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "body": {
                        "action": "create",
                        "payload": {"title": "Newer", "sections": [{"id": "main", "title": "", "tasks": []}]},
                    },
                },
            )
            older_id = first["json"]["checklist"]["id"]
            newer_id = second["json"]["checklist"]["id"]

            run_json_entrypoint(
                app_root / "backend" / "app_backend.py",
                cwd=app_root,
                payload={
                    "app_id": "checklist",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "body": {
                        "action": "update",
                        "id": older_id,
                        "payload": {
                            "title": "Older edited",
                            "sections": [{"id": "main", "title": "", "tasks": []}],
                        },
                    },
                },
            )
            listed = run_json_entrypoint(
                app_root / "backend" / "app_backend.py",
                cwd=app_root,
                payload={
                    "app_id": "checklist",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "body": {"action": "list"},
                },
            )

        self.assertEqual(listed["status_code"], 200)
        self.assertEqual([item["id"] for item in listed["json"]["items"]], [newer_id, older_id])

    def test_reference_tools_search_resolve_and_summarize_checklists(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            created = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "checklist",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "checklist_create",
                    "arguments": {
                        "payload": {
                            "title": "Agency launch",
                            "summary": "Delivery plan",
                            "sections": [
                                {
                                    "id": "main",
                                    "title": "Main",
                                    "tasks": [{"id": "task-1", "title": "Ship widget", "checked": True}],
                                }
                            ],
                        }
                    },
                },
            )
            checklist_id = created["checklist"]["id"]
            searched = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "checklist",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "checklist_reference_search",
                    "arguments": {"query": "agency"},
                },
            )
            resolved = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "checklist",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "checklist_reference_resolve",
                    "arguments": {"entity_type": "checklist", "entity_id": checklist_id},
                },
            )
            summarized = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "checklist",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "checklist_reference_summarize",
                    "arguments": {"entity_type": "checklist", "entity_id": checklist_id},
                },
            )

        self.assertEqual(searched["status_code"], 200)
        self.assertEqual(searched["results"][0]["entity_id"], checklist_id)
        self.assertTrue(resolved["exists"])
        self.assertEqual(resolved["title"], "Agency launch")
        self.assertIn("1/1 checked", summarized["summary"])

    def test_checklist_view_cli_persists_and_reads_board_view_state(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            created = run_json_entrypoint(
                app_root / "backend" / "app_backend.py",
                cwd=app_root,
                payload={
                    "app_id": "checklist",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "body": {
                        "action": "create",
                        "payload": {
                            "title": "Curated board",
                            "sections": [{"id": "main", "title": "", "tasks": []}],
                        },
                    },
                },
            )
            checklist_id = created["json"]["checklist"]["id"]
            custom = run_json_entrypoint(
                app_root / "cli" / "app_cli.py",
                cwd=app_root,
                payload={
                    "app_id": "checklist",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "command_id": "app.checklist.checklist-view",
                    "arguments": {
                        "action": "set_custom_view",
                        "title": "Pinned launch",
                        "refs": [{"app_id": "checklist", "entity_type": "checklist", "entity_id": checklist_id}],
                    },
                },
            )
            current = run_json_entrypoint(
                app_root / "cli" / "app_cli.py",
                cwd=app_root,
                payload={
                    "app_id": "checklist",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "command_id": "app.checklist.checklist-view",
                    "arguments": {},
                },
            )
            listed = run_json_entrypoint(
                app_root / "backend" / "app_backend.py",
                cwd=app_root,
                payload={
                    "app_id": "checklist",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "body": {"action": "list"},
                },
            )

        self.assertEqual(custom["status_code"], 200)
        self.assertEqual(current["view_state"]["mode"], "custom")
        self.assertEqual(current["view_state"]["title"], "Pinned launch")
        self.assertEqual(len(listed["json"]["items"]), 1)
        self.assertEqual(listed["json"]["items"][0]["id"], checklist_id)


if __name__ == "__main__":
    unittest.main()
