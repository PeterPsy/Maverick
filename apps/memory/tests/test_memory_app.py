"""Tests for the Memory app."""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from core.app_sdk.cli import main as maverick_cli_main
from core.apps.contracts import parse_app_contract_file
from core.api.platform_state import bootstrap_platform_state
from core.cli.models import CliInvocationContext
from core.cli.service import run_core_cli_command
from core.mcp.models import McpInvocationContext
from core.mcp.service import call_mcp_tool
from core.shared.entrypoints import run_json_entrypoint
from tests.support.markers import full_test, integration_test


REPO_ROOT = Path(__file__).resolve().parents[3]
MEMORY_ROOT = REPO_ROOT / "apps" / "memory"


class MemoryAppTestCase(unittest.TestCase):
    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick"
        for name in ("core", "apps", "workspaces", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        for app_id in ("base-shell", "chat", "memory"):
            shutil.copytree(
                REPO_ROOT / "apps" / app_id,
                repo_root / "apps" / app_id,
                ignore=shutil.ignore_patterns("node_modules", "__pycache__"),
            )
        return repo_root

    def run_backend(self, data_root: Path, body: dict) -> dict:
        result = run_json_entrypoint(
            MEMORY_ROOT / "backend" / "app_backend.py",
            payload={"data_root": str(data_root), "body": body},
            cwd=MEMORY_ROOT,
        )
        self.assertIn("json", result)
        return result

    def run_maverick_cli(self, argv: list[str], *, cwd: Path) -> dict:
        original_cwd = Path.cwd()
        output = StringIO()
        try:
            os.chdir(cwd)
            with redirect_stdout(output):
                exit_code = maverick_cli_main(argv)
        finally:
            os.chdir(original_cwd)
        self.assertEqual(exit_code, 0)
        return json.loads(output.getvalue())

    def run_maverick_cli_text(self, argv: list[str], *, cwd: Path) -> str:
        original_cwd = Path.cwd()
        output = StringIO()
        try:
            os.chdir(cwd)
            with redirect_stdout(output):
                exit_code = maverick_cli_main(argv)
        finally:
            os.chdir(original_cwd)
        self.assertEqual(exit_code, 0)
        return output.getvalue()

    def import_backend_module(self, module_name: str):
        import importlib
        import sys

        backend_path = str(MEMORY_ROOT / "backend")
        sys.path.insert(0, backend_path)
        try:
            return importlib.import_module(module_name)
        finally:
            sys.path.remove(backend_path)

    def test_contract_declares_memory_surfaces_and_reference_entities(self) -> None:
        parsed = parse_app_contract_file(MEMORY_ROOT)

        self.assertEqual(parsed.app_id, "memory")
        self.assertEqual(parsed.contract.entrypoints.backend, "backend/app_backend.py")
        self.assertEqual(parsed.contract.entrypoints.frontend, "frontend/dist")
        self.assertIn("memory_context", parsed.contract.capabilities.mcp_tools)
        self.assertIn("memory_compile", parsed.contract.capabilities.mcp_tools)
        self.assertIn("memory_lint", parsed.contract.capabilities.mcp_tools)
        self.assertIn("memory_wiki_query", parsed.contract.capabilities.mcp_tools)
        self.assertIn("memory_reference_manifest", parsed.contract.capabilities.mcp_tools)
        self.assertIn("memory_set_view_filter", parsed.contract.capabilities.mcp_tools)
        self.assertEqual(parsed.contract.capabilities.cli_commands, ["memory"])
        self.assertEqual(parsed.contract.storage.storage_kind, "sqlite+files")
        self.assertEqual(parsed.contract.storage.data_schema_version, "2")
        self.assertEqual(parsed.contract.capabilities.reference_entities[0].entity_type, "node")
        view_surface = parsed.contract.capabilities.view_surfaces[0]
        self.assertEqual(view_surface.view_id, "memory")
        self.assertEqual(view_surface.entity_types, ["node"])
        self.assertEqual(
            [action.action for action in view_surface.state_actions],
            ["view_filter", "set_view_filter", "set_custom_view", "clear_custom_view"],
        )
        widgets = {widget.widget_id: widget for widget in parsed.contract.widgets}
        self.assertEqual({"memory-sidebar", "memory-sidebar-footer"}, set(widgets))
        self.assertEqual(widgets["memory-sidebar"].host, "base-shell")
        self.assertEqual(widgets["memory-sidebar"].content_kinds, ["shell.sidebar.primary"])
        self.assertEqual(widgets["memory-sidebar"].frontend.mount, "frontend/dist/widgets/memory-sidebar")
        self.assertEqual(widgets["memory-sidebar-footer"].content_kinds, ["shell.sidebar.footer"])
        self.assertEqual(widgets["memory-sidebar-footer"].frontend.mount, "frontend/dist/widgets/memory-sidebar-footer")
        self.assertTrue((MEMORY_ROOT / "frontend" / "src" / "MemoryApp.tsx").is_file())
        dist_index = (MEMORY_ROOT / "frontend" / "dist" / "index.html").read_text(encoding="utf-8")
        self.assertIn("/apps/memory/assets/", dist_index)
        self.assertTrue((MEMORY_ROOT / "frontend" / "dist" / "widgets" / "memory-sidebar" / "index.html").is_file())
        self.assertTrue((MEMORY_ROOT / "frontend" / "dist" / "widgets" / "memory-sidebar-footer" / "index.html").is_file())

    def test_install_hook_is_idempotent_and_creates_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            payload = {"data_root": str(data_root)}

            first = run_json_entrypoint(MEMORY_ROOT / "hooks" / "install.py", payload=payload, cwd=MEMORY_ROOT)
            second = run_json_entrypoint(MEMORY_ROOT / "hooks" / "install.py", payload=payload, cwd=MEMORY_ROOT)

            self.assertEqual(first["status"], "ok")
            self.assertEqual(second["status"], "ok")
            self.assertTrue((data_root / "memory.sqlite").is_file())
            self.assertTrue((data_root / "artifacts" / "extracted").is_dir())
            health = run_json_entrypoint(MEMORY_ROOT / "hooks" / "health_check.py", payload=payload, cwd=MEMORY_ROOT)
            self.assertEqual(health["schema_version"], "2")

    def test_sqlite_wal_cache_tracks_recreated_database_file(self) -> None:
        database = self.import_backend_module("database")

        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            database._WAL_CONFIGURED_PATHS.clear()
            database.ensure_schema(data_root)
            db_file = database.db_path(data_root)
            first_signature = database.sqlite_file_signature(db_file)
            self.assertEqual(database._WAL_CONFIGURED_PATHS[db_file.resolve(strict=False)], first_signature)

            for path in (db_file, Path(f"{db_file}-wal"), Path(f"{db_file}-shm")):
                path.unlink(missing_ok=True)

            database.ensure_schema(data_root)
            second_signature = database.sqlite_file_signature(db_file)
            self.assertEqual(database._WAL_CONFIGURED_PATHS[db_file.resolve(strict=False)], second_signature)
            with database.connect(data_root) as db:
                journal_mode = db.execute("PRAGMA journal_mode").fetchone()[0]
            self.assertEqual(journal_mode.lower(), "wal")

    def test_storage_error_logging_is_structured_and_safe(self) -> None:
        import sqlite3

        entrypoint_errors = self.import_backend_module("entrypoint_errors")

        with self.assertLogs("maverick.memory", level="ERROR") as logs:
            status_code, payload = entrypoint_errors.storage_error_response(
                sqlite3.OperationalError("token value leaked"),
                app_id="memory-fork",
                action="remember",
            )

        event = json.loads(logs.records[0].getMessage())
        self.assertEqual(status_code, 500)
        self.assertEqual(payload["error"], "storage_error")
        self.assertEqual(event["event"], "memory_storage_error")
        self.assertEqual(event["app_id"], "memory-fork")
        self.assertEqual(event["action"], "remember")
        self.assertEqual(event["error_type"], "OperationalError")
        self.assertEqual(event["detail"], "[redacted]")

    def test_memory_end_to_end_retrieves_linked_file_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            first_result = self.run_backend(
                data_root,
                {
                    "action": "remember",
                    "title": "Stato bando X",
                    "body": "Il bando X e in revisione tecnica. Mancano allegati economici.",
                    "type": "note",
                },
            )
            first = first_result["json"]
            file_result = self.run_backend(
                data_root,
                {
                    "action": "attach_file",
                    "node_id": first["node"]["id"],
                    "file_id": "uploaded:bando-x.pdf",
                    "workspace_relative_path": "storage/uploaded/bando-x.pdf",
                    "title": "Bando X.pdf",
                },
            )
            file_ref = file_result["json"]
            second_result = self.run_backend(
                data_root,
                {
                    "action": "remember",
                    "title": "Referente bando X",
                    "body": "Mario Rossi segue la parte tecnica del bando X.",
                    "type": "person_ref",
                },
            )
            second = second_result["json"]
            edge_result = self.run_backend(
                data_root,
                {
                    "action": "link",
                    "source_node_id": first["node"]["id"],
                    "target_node_id": second["node"]["id"],
                    "kind": "mentions",
                    "weight": 0.8,
                    "confidence": 0.9,
                    "reason": "La persona e citata nello stato del bando.",
                },
            )
            edge = edge_result["json"]
            context_result = self.run_backend(data_root, {"action": "context", "query": "come siamo messi col bando X?"})
            context = context_result["json"]
            graph_result = self.run_backend(data_root, {"action": "graph"})
            graph = graph_result["json"]

            self.assertEqual(first_result["status_code"], 200)
            self.assertEqual(file_result["status_code"], 200)
            self.assertEqual(second_result["status_code"], 200)
            self.assertEqual(edge_result["status_code"], 200)
            self.assertEqual(file_ref["external_ref"]["workspace_relative_path"], "storage/uploaded/bando-x.pdf")
            self.assertEqual(edge["edge"]["kind"], "mentions")
            self.assertEqual(context_result["status_code"], 200)
            titles = {item["title"] for item in context["items"]}
            self.assertIn("Stato bando X", titles)
            self.assertTrue(any(ref.get("workspace_relative_path") == "storage/uploaded/bando-x.pdf" for item in context["items"] for ref in item["provenance"]))
            self.assertEqual(graph_result["status_code"], 200)
            self.assertEqual(len(graph["nodes"]), 2)
            self.assertEqual(len(graph["edges"]), 1)
            self.assertEqual(graph["edges"][0]["kind"], "mentions")

    def test_compile_builds_internal_wiki_context_and_search_matches(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            node = self.run_backend(
                data_root,
                {
                    "action": "remember",
                    "title": "Acme support agreement",
                    "body": "Acme signed the 2026 support agreement. Renewal owner is the platform team.",
                    "type": "fact",
                },
            )["json"]["node"]
            file_ref = self.run_backend(
                data_root,
                {
                    "action": "attach_file",
                    "node_id": node["id"],
                    "file_id": "file_acme_support",
                    "workspace_relative_path": "storage/generated/reports/acme-support.md",
                    "title": "Acme support source",
                },
            )["json"]["external_ref"]

            compiled = self.run_backend(data_root, {"action": "compile", "node_id": node["id"]})
            inspect = self.run_backend(data_root, {"action": "inspect", "node_id": node["id"]})
            context = self.run_backend(data_root, {"action": "context", "query": "renewal owner"})
            search = self.run_backend(data_root, {"action": "search", "query": "renewal owner"})
            wiki_query = self.run_backend(data_root, {"action": "wiki_query", "query": "support agreement"})

            self.assertEqual(compiled["status_code"], 200)
            self.assertEqual(compiled["json"]["compiled_page"]["title"], "Acme support agreement")
            self.assertEqual(compiled["json"]["claims"][0]["citations"][0]["external_ref_id"], file_ref["id"])
            self.assertFalse(any(finding["finding_type"] == "missing_citation" for finding in compiled["json"]["lint_findings"]))
            self.assertEqual(inspect["json"]["node"]["compiled_page"]["node_id"], node["id"])
            self.assertTrue(inspect["json"]["node"]["sources"])
            self.assertEqual(context["status_code"], 200)
            self.assertEqual(context["json"]["items"][0]["compiled"]["wiki_page_id"], compiled["json"]["compiled_page"]["id"])
            self.assertIn("claim", search["json"]["results"][0]["match_sources"])
            self.assertEqual(wiki_query["json"]["results"][0]["kind"], "wiki_page")

    def test_lint_reports_uncited_claims_and_contradictions(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            first = self.run_backend(
                data_root,
                {"action": "remember", "title": "Launch date", "body": "Launch is planned for June.", "type": "fact"},
            )["json"]["node"]
            second = self.run_backend(
                data_root,
                {"action": "remember", "title": "Launch conflict", "body": "Launch is blocked until July.", "type": "fact"},
            )["json"]["node"]
            self.run_backend(
                data_root,
                {
                    "action": "link",
                    "source_node_id": first["id"],
                    "target_node_id": second["id"],
                    "kind": "contradicts",
                    "reason": "The dates disagree.",
                },
            )

            self.run_backend(data_root, {"action": "compile", "node_id": first["id"]})
            lint = self.run_backend(data_root, {"action": "lint", "node_id": first["id"]})
            missing_lint = self.run_backend(data_root, {"action": "lint", "node_id": "node_missing"})

            self.assertEqual(lint["status_code"], 200)
            finding_types = {finding["finding_type"] for finding in lint["json"]["findings"]}
            self.assertIn("missing_citation", finding_types)
            self.assertIn("contradiction", finding_types)
            self.assertTrue(lint["json"]["summary"]["has_errors"])
            self.assertEqual(missing_lint["status_code"], 400)

    def test_backend_normalizes_errors_and_keeps_graph_payload_light(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            node = self.run_backend(data_root, {"action": "remember", "title": "Acme", "body": "Acme context."})["json"]["node"]
            self.run_backend(
                data_root,
                {
                    "action": "attach_file",
                    "node_id": node["id"],
                    "workspace_relative_path": "storage/uploaded/acme.txt",
                    "title": "Acme.txt",
                },
            )

            invalid_limit = self.run_backend(data_root, {"action": "graph", "limit": "many"})
            invalid_importance = self.run_backend(data_root, {"action": "remember", "title": "Bad", "importance": "high"})
            invalid_nan = self.run_backend(data_root, {"action": "remember", "title": "NaN", "importance": "nan"})
            duplicate_id = self.run_backend(data_root, {"action": "remember", "node_id": node["id"], "title": "Duplicate"})
            missing_delete = self.run_backend(data_root, {"action": "delete_node", "node_id": "node_missing"})
            missing_unlink = self.run_backend(data_root, {"action": "unlink", "edge_id": "edge_missing"})
            graph = self.run_backend(data_root, {"action": "graph"})
            inspect = self.run_backend(data_root, {"action": "inspect", "node_id": node["id"]})

            self.assertEqual(invalid_limit["status_code"], 400)
            self.assertEqual(invalid_limit["json"]["error"], "validation_error")
            self.assertEqual(invalid_importance["status_code"], 400)
            self.assertEqual(invalid_nan["status_code"], 400)
            self.assertIn("finite", invalid_nan["json"]["detail"])
            self.assertEqual(duplicate_id["status_code"], 400)
            self.assertEqual(duplicate_id["json"]["error"], "validation_error")
            self.assertEqual(missing_delete["status_code"], 400)
            self.assertEqual(missing_unlink["status_code"], 400)
            self.assertNotIn("external_refs", graph["json"]["nodes"][0])
            self.assertEqual(inspect["json"]["node"]["external_refs"][0]["title"], "Acme.txt")

    def test_context_read_does_not_write_audit_event_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            self.run_backend(data_root, {"action": "remember", "title": "Bando", "body": "Bando context."})
            context = self.run_backend(data_root, {"action": "context", "query": "Bando"})
            audit = self.run_backend(data_root, {"action": "audit"})

            self.assertEqual(context["status_code"], 200)
            self.assertTrue(context["json"]["items"])
            event_types = [event["event_type"] for event in audit["json"]["events"]]
            self.assertIn("node_created", event_types)
            self.assertNotIn("retrieval_context_generated", event_types)

    def test_reference_deep_links_use_local_app_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            node = self.run_backend(data_root, {"action": "remember", "title": "Forked memory", "body": "Local app id."})["json"]["node"]
            result = run_json_entrypoint(
                MEMORY_ROOT / "backend" / "app_backend.py",
                payload={
                    "app_id": "memory-fork",
                    "data_root": str(data_root),
                    "body": {"action": "references.search", "query": "Forked"},
                },
                cwd=MEMORY_ROOT,
            )
            custom = run_json_entrypoint(
                MEMORY_ROOT / "backend" / "app_backend.py",
                payload={
                    "app_id": "memory-fork",
                    "data_root": str(data_root),
                    "body": {
                        "action": "set_custom_view",
                        "refs": [{"app_id": "memory-fork", "entity_type": "node", "entity_id": node["id"]}],
                    },
                },
                cwd=MEMORY_ROOT,
            )

            self.assertEqual(result["status_code"], 200)
            self.assertEqual(result["json"]["results"][0]["app_id"], "memory-fork")
            self.assertEqual(result["json"]["results"][0]["deep_link"], f"/app/memory-fork/nodes/{node['id']}")
            self.assertEqual(custom["status_code"], 200)
            self.assertEqual(custom["json"]["state"]["view_filter"]["refs"], [{"entity_type": "node", "entity_id": node["id"]}])

    def test_backend_persists_view_filter_and_custom_memory_view(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            first = self.run_backend(data_root, {"action": "remember", "title": "Acme", "body": "Acme context."})["json"]["node"]
            second = self.run_backend(data_root, {"action": "remember", "title": "CEIDA", "body": "CEIDA context."})["json"]["node"]

            filtered = self.run_backend(data_root, {"action": "set_view_filter", "query": "Acme"})
            view_filter = self.run_backend(data_root, {"action": "view_filter"})
            custom = self.run_backend(
                data_root,
                {
                    "action": "set_custom_view",
                    "title": "Acme only",
                    "refs": [{"app_id": "memory", "entity_type": "node", "entity_id": first["id"]}],
                },
            )
            graph = self.run_backend(data_root, {"action": "graph", "node_ids": [first["id"]]})

            self.assertEqual(filtered["status_code"], 200)
            self.assertEqual(filtered["json"]["state"]["view_filter"]["query"], "Acme")
            self.assertEqual(view_filter["json"]["state"]["view_filter"]["query"], "Acme")
            self.assertEqual(custom["json"]["state"]["view_filter"]["mode"], "custom")
            self.assertEqual(custom["json"]["state"]["view_filter"]["title"], "Acme only")
            self.assertEqual(custom["json"]["state"]["view_filter"]["refs"], [{"entity_type": "node", "entity_id": first["id"]}])
            self.assertEqual([node["id"] for node in graph["json"]["nodes"]], [first["id"]])
            self.assertNotIn(second["id"], [node["id"] for node in graph["json"]["nodes"]])

    def test_backend_cli_and_mcp_entrypoints_share_memory_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            backend = run_json_entrypoint(
                MEMORY_ROOT / "backend" / "app_backend.py",
                payload={"data_root": str(data_root), "body": {"action": "remember", "title": "Company info", "body": "Acme works on bando X."}},
                cwd=MEMORY_ROOT,
            )
            cli = run_json_entrypoint(
                MEMORY_ROOT / "cli" / "app_cli.py",
                payload={"workspace_id": "default", "app_id": "memory", "data_root": str(data_root), "command_id": "app.memory.memory", "arguments": {"action": "context", "query": "Acme bando"}},
                cwd=MEMORY_ROOT,
            )
            mcp = run_json_entrypoint(
                MEMORY_ROOT / "mcp" / "server.py",
                payload={"workspace_id": "default", "app_id": "memory", "data_root": str(data_root), "tool_name": "memory_reference_manifest", "arguments": {}},
                cwd=MEMORY_ROOT,
            )
            view_filter = run_json_entrypoint(
                MEMORY_ROOT / "cli" / "app_cli.py",
                payload={"workspace_id": "default", "app_id": "memory", "data_root": str(data_root), "command_id": "app.memory.memory", "arguments": {"action": "set_view_filter", "query": "Acme"}},
                cwd=MEMORY_ROOT,
            )

            self.assertEqual(backend["status_code"], 200)
            self.assertEqual(cli["status_code"], 200)
            self.assertTrue(cli["items"])
            self.assertEqual(mcp["app_id"], "memory")
            self.assertEqual(mcp["entity_types"][0]["entity_type"], "node")
            self.assertEqual(view_filter["state"]["view_filter"]["query"], "Acme")

    @integration_test("memory platform integration suite; run with scripts/test_suite.py --level integration")
    def test_core_mounted_cli_and_mcp_can_use_memory(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        context = CliInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id="default",
            agent_id="agent-1",
            effective_mode="sandbox",
        )
        mcp_context = McpInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id="default",
            agent_id="agent-1",
            effective_mode="sandbox",
        )

        remembered = run_core_cli_command(
            command_id="app.memory.memory",
            context=context,
            app_store=state.app_store,
            workspace_store=state.workspace_store,
            workspace_id="default",
            start_path=repo_root,
            arguments={"action": "remember", "title": "Bando X", "body": "Il bando X ha una scadenza tecnica."},
        )
        context_payload = call_mcp_tool(
            tool_name="app.memory.memory_context",
            context=mcp_context,
            app_store=state.app_store,
            workspace_id="default",
            start_path=repo_root,
            arguments={"query": "scadenza bando X"},
        )

        self.assertEqual(remembered["status_code"], 200)
        self.assertEqual(remembered["node"]["title"], "Bando X")
        self.assertEqual(context_payload["status_code"], 200)
        self.assertTrue(context_payload["items"])

    @full_test("full memory wrapper suite; run with scripts/test_suite.py --level full")
    def test_maverick_wrapper_invokes_workspace_app_cli_and_mcp_without_app_paths(self) -> None:
        repo_root = self.make_repo_root()
        workspace_root = repo_root / "workspaces" / "default"
        workspace_root.mkdir(parents=True, exist_ok=True)

        remembered = self.run_maverick_cli(
            [
                "--repository-root",
                str(repo_root),
                "app",
                "memory",
                "cli",
                "run",
                "memory",
                "--action",
                "remember",
                "--title",
                "Acme",
                "--body",
                "Acme has a workspace memory note.",
            ],
            cwd=workspace_root,
        )
        cli_context = self.run_maverick_cli(
            [
                "--repository-root",
                str(repo_root),
                "app",
                "memory",
                "cli",
                "run",
                "memory",
                "--action",
                "context",
                "--query",
                "Acme",
            ],
            cwd=workspace_root,
        )
        mcp_context = self.run_maverick_cli(
            [
                "--repository-root",
                str(repo_root),
                "app",
                "memory",
                "mcp",
                "call",
                "memory_context",
                "--query",
                "Acme",
            ],
            cwd=workspace_root,
        )

        self.assertEqual(remembered["status_code"], 200)
        self.assertEqual(remembered["node"]["title"], "Acme")
        apps_list = self.run_maverick_cli(
            ["--repository-root", str(repo_root), "apps", "list", "--json"],
            cwd=workspace_root,
        )
        self.assertIn("memory", [app["app_id"] for app in apps_list["apps"]])
        help_text = self.run_maverick_cli_text(
            ["--repository-root", str(repo_root), "app", "memory", "cli", "--help"],
            cwd=workspace_root,
        )
        self.assertIn("maverick app memory cli list --json", help_text)
        self.assertIn("list` and `inspect`", self.run_maverick_cli_text(["--help"], cwd=workspace_root))
        cli_list = self.run_maverick_cli(
            ["--repository-root", str(repo_root), "app", "memory", "cli", "list", "--json"],
            cwd=workspace_root,
        )
        self.assertEqual(cli_list["commands"][0]["name"], "memory")
        cli_inspect = self.run_maverick_cli(
            ["--repository-root", str(repo_root), "app", "memory", "cli", "inspect", "memory", "--json"],
            cwd=workspace_root,
        )
        self.assertEqual(cli_inspect["command"]["name"], "memory")
        mcp_list = self.run_maverick_cli(
            ["--repository-root", str(repo_root), "app", "memory", "mcp", "list", "--json"],
            cwd=workspace_root,
        )
        self.assertIn("memory_context", [tool["name"] for tool in mcp_list["tools"]])
        mcp_inspect = self.run_maverick_cli(
            ["--repository-root", str(repo_root), "app", "memory", "mcp", "inspect", "memory_context", "--json"],
            cwd=workspace_root,
        )
        self.assertEqual(mcp_inspect["tool"]["name"], "memory_context")
        with self.assertRaises(SystemExit):
            self.run_maverick_cli(
                ["--repository-root", str(repo_root), "app", "cli", "memory", "--action", "context", "--query", "Acme"],
                cwd=workspace_root,
            )
        self.assertEqual(cli_context["status_code"], 200)
        self.assertTrue(cli_context["items"])
        self.assertEqual(mcp_context["status_code"], 200)
        self.assertTrue(mcp_context["items"])
