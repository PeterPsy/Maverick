"""Generated contract smoke test."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from core.apps.contracts import parse_app_contract_file
from core.apps.surface_descriptors import app_cli_command_metadata, app_mcp_tool_metadata
from core.shared.entrypoints import run_json_entrypoint


class GeneratedAppContractTest(unittest.TestCase):
    def test_contract_parses(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        parsed = parse_app_contract_file(app_root)
        self.assertEqual(parsed.app_id, "checklist")
        self.assertEqual(parsed.contract.storage.data_schema_version, "4")
        self.assertEqual(parsed.contract.capabilities.cli_commands, ["checklist", "checklist-reference", "checklist-view"])
        self.assertIn("checklist_reference_search", parsed.contract.capabilities.mcp_tools)
        self.assertIn("checklist_set_custom_view", parsed.contract.capabilities.mcp_tools)
        self.assertIn("checklist_set_task_status", parsed.contract.capabilities.mcp_tools)
        self.assertIn("checklist_next_actions", parsed.contract.capabilities.mcp_tools)
        self.assertEqual(parsed.contract.capabilities.reference_entities[0].entity_type, "checklist")
        surface = parsed.contract.capabilities.view_surfaces[0]
        self.assertEqual(surface.view_id, "main")
        self.assertEqual(surface.entity_types, ["checklist"])
        actions = {item.action: item for item in surface.state_actions}
        self.assertTrue(actions["set_custom_view"].standard)
        self.assertTrue(actions["set_view_filter"].standard)
        self.assertTrue(surface.supports_custom_view)
        widgets = {widget.widget_id: widget for widget in parsed.contract.widgets}
        self.assertEqual(widgets["checklist-sidebar"].host, "base-shell")
        self.assertEqual(widgets["checklist-sidebar"].content_kinds, ["shell.sidebar.primary"])
        self.assertEqual(widgets["checklist-sidebar-footer"].host, "base-shell")
        self.assertEqual(widgets["checklist-sidebar-footer"].content_kinds, ["shell.sidebar.footer"])
        self.assertEqual(widgets["design-checklist"].host, "chat")
        self.assertEqual(widgets["design-checklist"].content_kinds, ["checklist.design"])

    def test_cli_and_mcp_descriptors_are_agent_friendly(self) -> None:
        app_root = Path(__file__).resolve().parents[1]

        cli_description, cli_schema = app_cli_command_metadata(
            app_root,
            "checklist",
            default_description="fallback",
        )
        tool_description, tool_input_schema, tool_output_schema = app_mcp_tool_metadata(
            app_root,
            "checklist_create",
            default_description="fallback",
        )

        self.assertIn("operations manifest", cli_description)
        self.assertEqual(cli_schema["properties"]["action"]["default"], "operations.manifest")
        self.assertIn("operations.manifest", cli_schema["properties"]["action"]["enum"])
        self.assertIn("oneOf", cli_schema)
        self.assertIn("Create one workspace checklist", tool_description)
        self.assertIn({"required": ["title"]}, tool_input_schema["anyOf"])
        self.assertIn({"required": ["payload"]}, tool_input_schema["anyOf"])
        self.assertFalse(tool_input_schema["additionalProperties"])
        self.assertEqual(tool_output_schema["properties"]["checklist"]["type"], "object")

    def test_cli_default_returns_compact_operations_manifest(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            result = run_json_entrypoint(
                app_root / "cli" / "app_cli.py",
                cwd=app_root,
                payload={
                    "app_id": "checklist",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "command_id": "app.checklist.checklist",
                    "arguments": {},
                },
            )

        self.assertEqual(result["status_code"], 200)
        self.assertEqual(result["action"], "operations.manifest")
        self.assertEqual(result["default_action"], "operations.manifest")
        self.assertIn("checklist_create", [item["name"] for item in result["tools"]])
        self.assertEqual(result["payload_profiles"]["list"], "compact_by_default")
        self.assertNotIn("items", result)

    def test_list_is_compact_by_default_and_full_content_is_explicit(self) -> None:
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
                            "title": "Payload budget",
                            "metadata": {"large": "x" * 1000},
                            "sections": [
                                {
                                    "id": "main",
                                    "title": "Main",
                                    "tasks": [{"id": "task-1", "title": "Ship compact list", "checked": False}],
                                }
                            ],
                        },
                    },
                },
            )
            compact = run_json_entrypoint(
                app_root / "backend" / "app_backend.py",
                cwd=app_root,
                payload={
                    "app_id": "checklist",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "body": {"action": "list"},
                },
            )
            full = run_json_entrypoint(
                app_root / "backend" / "app_backend.py",
                cwd=app_root,
                payload={
                    "app_id": "checklist",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "body": {"action": "list", "include_content": True},
                },
            )

        self.assertEqual(created["status_code"], 201)
        self.assertEqual(compact["status_code"], 200)
        self.assertEqual(compact["json"]["content_profile"], "compact")
        self.assertNotIn("sections", compact["json"]["items"][0])
        self.assertNotIn("metadata", compact["json"]["items"][0])
        self.assertEqual(full["json"]["content_profile"], "full")
        self.assertIn("sections", full["json"]["items"][0])
        self.assertIn("metadata", full["json"]["items"][0])

    def test_validation_errors_are_guided(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            unsupported = run_json_entrypoint(
                app_root / "backend" / "app_backend.py",
                cwd=app_root,
                payload={
                    "app_id": "checklist",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "body": {"action": "nope"},
                },
            )
            missing_id = run_json_entrypoint(
                app_root / "backend" / "app_backend.py",
                cwd=app_root,
                payload={
                    "app_id": "checklist",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "body": {"action": "read"},
                },
            )
            invalid_limit = run_json_entrypoint(
                app_root / "backend" / "app_backend.py",
                cwd=app_root,
                payload={
                    "app_id": "checklist",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "body": {"action": "list", "limit": "banana"},
                },
            )
            oversized_limit = run_json_entrypoint(
                app_root / "backend" / "app_backend.py",
                cwd=app_root,
                payload={
                    "app_id": "checklist",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "body": {"action": "list", "limit": 1000000},
                },
            )
            missing_record = run_json_entrypoint(
                app_root / "backend" / "app_backend.py",
                cwd=app_root,
                payload={
                    "app_id": "checklist",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "body": {"action": "update", "id": "check_missing"},
                },
            )

        self.assertEqual(unsupported["status_code"], 400)
        self.assertEqual(unsupported["json"]["error"], "unsupported_action")
        self.assertIn("allowed_values", unsupported["json"])
        self.assertEqual(unsupported["json"]["example"], {"action": "operations.manifest"})
        self.assertEqual(missing_id["status_code"], 400)
        self.assertEqual(missing_id["json"]["operation"], "read")
        self.assertEqual(missing_id["json"]["expected_fields"], ["id"])
        self.assertEqual(missing_id["json"]["accepted_aliases"], {"id": ["checklist_id"]})
        self.assertEqual(invalid_limit["status_code"], 400)
        self.assertEqual(invalid_limit["json"]["allowed_values"], {"limit": {"minimum": 1, "maximum": 500}})
        self.assertEqual(oversized_limit["status_code"], 400)
        self.assertIn("between 1 and 500", oversized_limit["json"]["detail"])
        self.assertEqual(missing_record["status_code"], 404)
        self.assertEqual(missing_record["json"]["error"], "not_found")
        self.assertEqual(missing_record["json"]["expected_fields"], [])
        self.assertEqual(missing_record["json"]["entity_id"], "check_missing")

    def test_checklist_tasklist_creates_chat_render_payload(self) -> None:
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
                    "tool_name": "checklist_tasklist",
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
        self.assertNotIn("legacy_kind", result["chat_render"])
        self.assertEqual(result["chat_render"]["payload"]["id"], result["checklist"]["id"])
        self.assertEqual(result["checklist"]["mode"], "simple")
        self.assertEqual(result["checklist"]["sections"][0]["tasks"][0]["status"], "pending")

    def test_agent_plan_payload_preserves_status_priority_dependencies_tools_and_subtasks(self) -> None:
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
                            "mode": "agent_plan",
                            "title": "Agent handoff",
                            "priority": "high",
                            "sections": [
                                {
                                    "id": "plan",
                                    "title": "Plan",
                                    "tasks": [
                                        {
                                            "id": "implement",
                                            "title": "Implement schema",
                                            "description": "Move checklist to agent-plan semantics.",
                                            "status": "in-progress",
                                            "priority": "critical",
                                            "dependencies": ["research"],
                                            "tools": ["shell", "file-system"],
                                            "blocked_reason": "Waiting for agent context.",
                                            "agent_ref": "agent:planner",
                                            "source_ref": "chat:thread-123",
                                            "agent_dialogs": [
                                                {
                                                    "id": "dialog-1",
                                                    "title": "Planner handoff",
                                                    "summary": "Agent explained the schema work.",
                                                    "ref": "chat:thread-123#turn-1",
                                                    "agent_ref": "agent:planner",
                                                }
                                            ],
                                            "subtasks": [
                                                {
                                                    "id": "tests",
                                                    "title": "Add tests",
                                                    "status": "pending",
                                                    "priority": "high",
                                                    "tools": ["test-runner"],
                                                    "agent_ref": "agent:tester",
                                                    "source_ref": "chat:thread-123#turn-2",
                                                    "agent_dialogs": ["chat:thread-123#turn-2"],
                                                }
                                            ],
                                        }
                                    ],
                                }
                            ],
                        }
                    },
                },
            )

        checklist = created["checklist"]
        task = checklist["sections"][0]["tasks"][0]
        self.assertEqual(checklist["mode"], "agent_plan")
        self.assertEqual(checklist["priority"], "high")
        self.assertEqual(task["status"], "in-progress")
        self.assertEqual(task["priority"], "critical")
        self.assertEqual(task["dependencies"], ["research"])
        self.assertEqual(task["tools"], ["shell", "file-system"])
        self.assertEqual(task["blocked_reason"], "Waiting for agent context.")
        self.assertEqual(task["agent_ref"], "agent:planner")
        self.assertEqual(task["source_ref"], "chat:thread-123")
        self.assertEqual(task["agent_dialogs"][0]["title"], "Planner handoff")
        self.assertEqual(task["subtasks"][0]["tools"], ["test-runner"])
        self.assertEqual(task["subtasks"][0]["agent_ref"], "agent:tester")
        self.assertEqual(task["subtasks"][0]["source_ref"], "chat:thread-123#turn-2")
        self.assertEqual(task["subtasks"][0]["agent_dialogs"][0]["ref"], "chat:thread-123#turn-2")
        self.assertEqual(checklist["task_count"], 2)

    def test_agent_status_tools_update_task_and_subtask_status(self) -> None:
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
                            "mode": "agent_plan",
                            "title": "Execution",
                            "sections": [
                                {
                                    "id": "main",
                                    "title": "Main",
                                    "tasks": [
                                        {
                                            "id": "task-1",
                                            "title": "Run build",
                                            "status": "pending",
                                            "subtasks": [{"id": "sub-1", "title": "Install deps", "status": "pending"}],
                                        }
                                    ],
                                }
                            ],
                        }
                    },
                },
            )
            checklist_id = created["checklist"]["id"]
            task_status = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "checklist",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "checklist_set_task_status",
                    "arguments": {
                        "id": checklist_id,
                        "section_id": "main",
                        "task_id": "task-1",
                        "status": "completed",
                    },
                },
            )
            subtask_status = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "checklist",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "checklist_set_subtask_status",
                    "arguments": {
                        "id": checklist_id,
                        "section_id": "main",
                        "task_id": "task-1",
                        "subtask_id": "sub-1",
                        "status": "blocked",
                    },
                },
            )
            reread = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "checklist",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "checklist_read",
                    "arguments": {"id": checklist_id},
                },
            )

        self.assertEqual(task_status["status_code"], 200)
        self.assertTrue(task_status["task"]["checked"])
        self.assertEqual(subtask_status["subtask"]["status"], "blocked")
        self.assertEqual(reread["checklist"]["checked_count"], 1)
        self.assertEqual(reread["checklist"]["blocked_count"], 1)

    def test_backend_updates_v3_style_sections(self) -> None:
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

    def test_backend_rejects_create_without_workspace_context(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            result = run_json_entrypoint(
                app_root / "backend" / "app_backend.py",
                cwd=app_root,
                payload={
                    "app_id": "checklist",
                    "data_root": str(data_root),
                    "body": {
                        "action": "create",
                        "payload": {
                            "title": "No workspace",
                            "sections": [{"id": "main", "title": "", "tasks": []}],
                        },
                    },
                },
            )

        self.assertEqual(result["status_code"], 400)
        self.assertEqual(result["json"]["error"], "validation_error")
        self.assertIn("workspace_id is required", result["json"]["detail"])

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

    def test_list_can_ignore_view_state_for_all_checklists_view(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            for title in ["Visible plan", "Hidden plan"]:
                run_json_entrypoint(
                    app_root / "backend" / "app_backend.py",
                    cwd=app_root,
                    payload={
                        "app_id": "checklist",
                        "workspace_id": "default",
                        "data_root": str(data_root),
                        "body": {
                            "action": "create",
                            "payload": {"title": title, "sections": [{"id": "main", "title": "", "tasks": []}]},
                        },
                    },
                )
            run_json_entrypoint(
                app_root / "backend" / "app_backend.py",
                cwd=app_root,
                payload={
                    "app_id": "checklist",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "body": {"action": "set_view_filter", "query": "Visible"},
                },
            )
            filtered = run_json_entrypoint(
                app_root / "backend" / "app_backend.py",
                cwd=app_root,
                payload={
                    "app_id": "checklist",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "body": {"action": "list"},
                },
            )
            unfiltered = run_json_entrypoint(
                app_root / "backend" / "app_backend.py",
                cwd=app_root,
                payload={
                    "app_id": "checklist",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "body": {"action": "list", "ignore_view_state": True},
                },
            )

        self.assertEqual([item["title"] for item in filtered["json"]["items"]], ["Visible plan"])
        self.assertEqual({item["title"] for item in unfiltered["json"]["items"]}, {"Visible plan", "Hidden plan"})

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
        self.assertEqual(searched["results"][0]["deep_link"], f"/app/checklist/checklists/{checklist_id}")
        self.assertEqual(resolved["app_page"], f"checklists/{checklist_id}")
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
