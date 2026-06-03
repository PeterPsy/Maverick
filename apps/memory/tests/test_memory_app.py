"""Tests for the Memory app."""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import shutil
import sys
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
MEMORY_BACKEND_ROOT = MEMORY_ROOT / "backend"
MEMORY_BACKEND_MODULE_NAMES = {path.stem for path in MEMORY_BACKEND_ROOT.glob("*.py")}


def evict_foreign_backend_modules() -> None:
    backend_root = MEMORY_BACKEND_ROOT.resolve()
    for name, module in list(sys.modules.items()):
        if name not in MEMORY_BACKEND_MODULE_NAMES:
            continue
        module_file = getattr(module, "__file__", None)
        if not module_file:
            continue
        try:
            resolved = Path(module_file).resolve()
        except OSError:
            continue
        if resolved != backend_root / resolved.name:
            sys.modules.pop(name, None)


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

        evict_foreign_backend_modules()
        backend_path = str(MEMORY_BACKEND_ROOT)
        sys.path.insert(0, backend_path)
        try:
            return importlib.import_module(module_name)
        finally:
            sys.path.remove(backend_path)

    def drive_memory_source(
        self,
        *,
        storage_file_id: str = "file_drive_plan",
        drive_file_id: str = "drive_plan",
        source_version: str = "rev-1",
    ) -> dict:
        return {
            "source_kind": "remote_storage_file",
            "owning_app_id": "storage",
            "entity_type": "file",
            "entity_id": storage_file_id,
            "file_id": storage_file_id,
            "workspace_relative_path": "",
            "metadata": {
                "provider": "google_drive",
                "connection_id": "drive_conn_acme",
                "drive_file_id": drive_file_id,
                "source_version": source_version,
                "display_path": "/Drive/Plans/Plan.md",
            },
        }

    def test_contract_declares_memory_surfaces_and_reference_entities(self) -> None:
        parsed = parse_app_contract_file(MEMORY_ROOT)

        self.assertEqual(parsed.app_id, "memory")
        self.assertEqual(parsed.contract.entrypoints.backend, "backend/app_backend.py")
        self.assertEqual(parsed.contract.entrypoints.frontend, "frontend/dist")
        self.assertIn("memory_context", parsed.contract.capabilities.mcp_tools)
        self.assertIn("memory_compile", parsed.contract.capabilities.mcp_tools)
        self.assertIn("memory_lint", parsed.contract.capabilities.mcp_tools)
        self.assertIn("memory_wiki_query", parsed.contract.capabilities.mcp_tools)
        self.assertIn("memory_ingest_storage_source", parsed.contract.capabilities.mcp_tools)
        self.assertIn("memory_apply_storage_staleness", parsed.contract.capabilities.mcp_tools)
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

    def test_cli_and_mcp_descriptors_cover_declared_agent_surfaces(self) -> None:
        parsed = parse_app_contract_file(MEMORY_ROOT)
        cli_descriptor = json.loads((MEMORY_ROOT / "cli" / "command_schemas.json").read_text(encoding="utf-8"))
        mcp_descriptor = json.loads((MEMORY_ROOT / "mcp" / "tool_schemas.json").read_text(encoding="utf-8"))

        self.assertEqual(sorted(cli_descriptor["commands"]), sorted(parsed.contract.capabilities.cli_commands))
        self.assertEqual(sorted(mcp_descriptor["tools"]), sorted(parsed.contract.capabilities.mcp_tools))
        attach_schema = mcp_descriptor["tools"]["memory_attach_file"]["input_schema"]
        self.assertIn("remote_storage_file", mcp_descriptor["tools"]["memory_attach_file"]["description"])
        self.assertEqual(attach_schema["properties"]["provider"]["enum"], ["google_drive", "local"])
        self.assertIn("source_version", attach_schema["properties"]["metadata"]["properties"])
        ingest_schema = mcp_descriptor["tools"]["memory_ingest_storage_source"]["input_schema"]
        self.assertIn("memory_source", ingest_schema["required"])
        self.assertEqual(
            ingest_schema["properties"]["memory_source"]["properties"]["source_kind"]["enum"],
            ["remote_storage_file"],
        )
        memory_source_schema = ingest_schema["properties"]["memory_source"]
        metadata_schema = memory_source_schema["properties"]["metadata"]
        self.assertNotIn("source_version", metadata_schema["required"])
        self.assertIn({"required": ["source_version"]}, ingest_schema["anyOf"])
        self.assertTrue(
            any(
                option.get("properties", {})
                .get("memory_source", {})
                .get("properties", {})
                .get("metadata", {})
                .get("required")
                == ["source_version"]
                for option in ingest_schema["anyOf"]
            )
        )
        staleness_schema = mcp_descriptor["tools"]["memory_apply_storage_staleness"]["input_schema"]
        self.assertIn("memory_staleness", staleness_schema["properties"])
        self.assertIn("entity_id", staleness_schema["properties"])

    def test_memory_skill_documents_drive_ingest_workflow(self) -> None:
        skill = (MEMORY_ROOT / "skills" / "memory-ops" / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("storage_drive_index", skill)
        self.assertIn("memory_ingest_storage_source", skill)
        self.assertIn("storage_drive_mark_indexed", skill)
        self.assertIn("memory_apply_storage_staleness", skill)
        self.assertIn("Memory never scans Drive itself", skill)

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
            self.assertEqual(file_ref["external_ref"]["ref_kind"], "local_storage_file")
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

    def test_compile_builds_internal_wiki_context_sources_and_search_matches(self) -> None:
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
            self.assertEqual(compiled["json"]["claims"][0]["citations"], [])
            self.assertEqual(compiled["json"]["citations"], [])
            self.assertTrue(any(source["external_ref_id"] == file_ref["id"] for source in compiled["json"]["sources"]))
            self.assertTrue(any(finding["finding_type"] == "missing_citation" for finding in compiled["json"]["lint_findings"]))
            self.assertEqual(inspect["json"]["node"]["compiled_page"]["node_id"], node["id"])
            self.assertTrue(inspect["json"]["node"]["sources"])
            self.assertEqual(context["status_code"], 200)
            self.assertEqual(context["json"]["items"][0]["compiled"]["wiki_page_id"], compiled["json"]["compiled_page"]["id"])
            self.assertIn("claim", search["json"]["results"][0]["match_sources"])
            self.assertEqual(wiki_query["json"]["results"][0]["kind"], "wiki_page")

    def test_node_reference_and_source_changes_mark_compiled_wiki_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace_root = Path(temp)
            data_root = workspace_root / "data" / "memory"
            source_path = workspace_root / "storage" / "generated" / "reports" / "acme-support.md"
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_text("Initial support source.", encoding="utf-8")
            node = self.run_backend(
                data_root,
                {
                    "action": "remember",
                    "title": "Acme source freshness",
                    "body": "Acme support is active.",
                    "type": "fact",
                },
            )["json"]["node"]
            self.run_backend(
                data_root,
                {
                    "action": "attach_file",
                    "node_id": node["id"],
                    "file_id": "file_acme_support",
                    "workspace_relative_path": "storage/generated/reports/acme-support.md",
                    "title": "Acme support source",
                },
            )

            compiled = self.run_backend(data_root, {"action": "compile", "node_id": node["id"]})["json"]
            source_path.write_text("Changed support source.", encoding="utf-8")
            lint_after_source_change = self.run_backend(data_root, {"action": "lint", "node_id": node["id"]})["json"]
            changed_source_inspect = self.run_backend(data_root, {"action": "inspect", "node_id": node["id"]})["json"]["node"]
            self.run_backend(data_root, {"action": "compile", "node_id": node["id"]})
            updated = self.run_backend(
                data_root,
                {"action": "update_node", "node_id": node["id"], "body": "Acme support owner changed."},
            )["json"]["node"]
            context = self.run_backend(data_root, {"action": "context", "query": "Acme support owner"})["json"]

            self.assertEqual(compiled["compiled_page"]["freshness"], "fresh")
            self.assertTrue(any(finding["finding_type"] == "stale_page" for finding in lint_after_source_change["findings"]))
            self.assertEqual(changed_source_inspect["compiled_page"]["freshness"], "stale")
            self.assertTrue(any(finding["finding_type"] == "stale_page" for finding in changed_source_inspect["lint_findings"]))
            self.assertEqual(updated["compiled_page"]["freshness"], "stale")
            self.assertTrue(any(finding["finding_type"] == "stale_page" for finding in updated["lint_findings"]))
            self.assertEqual(context["items"][0]["compiled"]["freshness"], "stale")

    def test_file_source_versions_use_observed_file_hashes_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace_root = Path(temp)
            data_root = workspace_root / "data" / "memory"
            source_path = workspace_root / "storage" / "generated" / "source.md"
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_text("first version", encoding="utf-8")
            node = self.run_backend(
                data_root,
                {"action": "remember", "title": "Versioned source", "body": "Source backed claim.", "type": "fact"},
            )["json"]["node"]
            self.run_backend(
                data_root,
                {
                    "action": "attach_file",
                    "node_id": node["id"],
                    "workspace_relative_path": "storage/generated/source.md",
                    "title": "Source",
                },
            )

            self.run_backend(data_root, {"action": "compile", "node_id": node["id"]})
            source_path.write_text("second version", encoding="utf-8")
            self.run_backend(data_root, {"action": "compile", "node_id": node["id"]})

            database = self.import_backend_module("database")
            with database.connect(data_root) as db:
                versions = [database.row_payload(row) or {} for row in db.execute("SELECT * FROM source_versions ORDER BY created_at")]

            self.assertEqual(len(versions), 2)
            self.assertEqual({version["metadata"]["hash_kind"] for version in versions}, {"file_bytes"})
            self.assertTrue(all(not version["extracted_text"] for version in versions))

    def test_attach_file_accepts_remote_storage_ref_without_workspace_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            node = self.run_backend(
                data_root,
                {"action": "remember", "title": "Drive contract", "body": "Drive source.", "type": "fact"},
            )["json"]["node"]

            attached = self.run_backend(
                data_root,
                {
                    "action": "attach_file",
                    "node_id": node["id"],
                    "owning_app_id": "storage",
                    "entity_type": "file",
                    "entity_id": "file_drive_contract",
                    "title": "Contract",
                    "metadata": {
                        "provider": "google_drive",
                        "connection_id": "drive_conn_acme",
                        "drive_file_id": "drive_file_contract",
                        "source_version": "rev-1",
                        "display_path": "/Contracts/Acme.pdf",
                    },
                },
            )
            rejected = self.run_backend(
                data_root,
                {
                    "action": "attach_file",
                    "node_id": node["id"],
                    "owning_app_id": "storage",
                    "entity_type": "file",
                    "entity_id": "file_drive_contract_2",
                    "workspace_relative_path": "storage/generated/drive-shadow.pdf",
                    "metadata": {
                        "provider": "google_drive",
                        "connection_id": "drive_conn_acme",
                        "drive_file_id": "drive_file_contract_2",
                    },
                },
            )

            remote_ref = attached["json"]["external_ref"]
            self.assertEqual(attached["status_code"], 200)
            self.assertEqual(remote_ref["ref_kind"], "remote_storage_file")
            self.assertEqual(remote_ref["owning_app_id"], "storage")
            self.assertEqual(remote_ref["entity_type"], "file")
            self.assertEqual(remote_ref["entity_id"], "file_drive_contract")
            self.assertEqual(remote_ref["workspace_relative_path"], "")
            self.assertEqual(remote_ref["metadata"]["provider"], "google_drive")
            self.assertEqual(rejected["status_code"], 400)
            self.assertIn("workspace_relative_path", rejected["json"]["detail"])

    def test_ingest_storage_source_creates_node_compiles_preview_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            storage_sources = self.import_backend_module("storage_sources")
            service = self.import_backend_module("service")
            database = self.import_backend_module("database")
            original_surface = storage_sources._storage_preview_surface
            try:
                storage_sources._storage_preview_surface = lambda _data_root, _request: (_ for _ in ()).throw(
                    AssertionError("ingested preview_text should avoid a second Storage preview")
                )
                status, first = service.handle_action(
                    data_root,
                    {
                        "action": "ingest_storage_source",
                        "title": "Drive renewal plan",
                        "memory_source": self.drive_memory_source(),
                        "preview_text": "Drive renewal plan says the renewal owner is Dana.",
                        "compile_after_ingest": True,
                    },
                )
                second_status, second = service.handle_action(
                    data_root,
                    {
                        "action": "ingest_storage_source",
                        "title": "Drive renewal plan duplicate",
                        "memory_source": self.drive_memory_source(),
                        "preview_text": "Drive renewal plan says the renewal owner is Dana.",
                    },
                )
                context_status, context = service.handle_action(data_root, {"action": "context", "query": "renewal owner"})
                search_status, search = service.handle_action(data_root, {"action": "search", "query": "Dana"})
                wiki_status, wiki_result = service.handle_action(data_root, {"action": "wiki_query", "query": "Dana"})
            finally:
                storage_sources._storage_preview_surface = original_surface

            with database.connect(data_root) as db:
                ref_count = db.execute("SELECT COUNT(*) AS count FROM external_refs").fetchone()["count"]
                version = database.row_payload(db.execute("SELECT * FROM source_versions").fetchone()) or {}
                source = database.row_payload(db.execute("SELECT * FROM sources").fetchone()) or {}

            self.assertEqual(status, 200)
            self.assertEqual(second_status, 200)
            self.assertTrue(first["node_created"])
            self.assertTrue(first["external_ref_created"])
            self.assertFalse(second["node_created"])
            self.assertFalse(second["external_ref_created"])
            self.assertEqual(second["node"]["id"], first["node"]["id"])
            self.assertEqual(ref_count, 1)
            self.assertEqual(first["compiled"]["compiled_page"]["freshness"], "fresh")
            self.assertTrue(first["compiled"]["citations"])
            self.assertEqual(first["compiled"]["citations"][0]["metadata"]["source_version"], "rev-1")
            self.assertEqual(first["compiled"]["citations"][0]["source_version"], "rev-1")
            self.assertEqual(
                first["compiled"]["citations"][0]["storage_reference"]["preview_request"]["tool"],
                "storage_drive_preview",
            )
            self.assertIn("renewal owner is Dana", version["extracted_text"])
            self.assertNotIn("ingest_preview_text", source["metadata"])
            self.assertNotIn("ingest_preview_truncated", source["metadata"])
            self.assertEqual(context_status, 200)
            self.assertEqual(search_status, 200)
            self.assertEqual(wiki_status, 200)
            context_ref = context["items"][0]["storage_references"][0]
            search_ref = search["results"][0]["storage_references"][0]
            wiki_ref = wiki_result["results"][0]["storage_references"][0]
            self.assertEqual(context_ref["stable_storage_file_id"], "file_drive_plan")
            self.assertEqual(search_ref["preview_request"]["arguments"]["stable_storage_file_id"], "file_drive_plan")
            self.assertEqual(wiki_ref["deep_link"], "/app/storage/files/file_drive_plan")
            self.assertEqual(context["items"][0]["compiled"]["storage_references"][0]["drive_file_id"], "drive_plan")

    def test_ingest_storage_source_accepts_empty_preview_text_without_second_storage_preview(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            storage_sources = self.import_backend_module("storage_sources")
            service = self.import_backend_module("service")
            database = self.import_backend_module("database")
            original_surface = storage_sources._storage_preview_surface
            try:
                storage_sources._storage_preview_surface = lambda _data_root, _request: (_ for _ in ()).throw(
                    AssertionError("empty drive_index preview_text is still an explicit Storage preview result")
                )
                status, result = service.handle_action(
                    data_root,
                    {
                        "action": "ingest_storage_source",
                        "title": "Empty Drive document",
                        "memory_source": self.drive_memory_source(
                            storage_file_id="file_drive_empty",
                            drive_file_id="drive_empty",
                            source_version="rev-empty",
                        ),
                        "preview_text": "",
                        "preview_truncated": False,
                        "compile_after_ingest": True,
                    },
                )
            finally:
                storage_sources._storage_preview_surface = original_surface

            with database.connect(data_root) as db:
                source = database.row_payload(db.execute("SELECT * FROM sources").fetchone()) or {}
                version = database.row_payload(db.execute("SELECT * FROM source_versions").fetchone()) or {}

            self.assertEqual(status, 200)
            self.assertEqual(result["compiled"]["compiled_page"]["freshness"], "fresh")
            self.assertEqual(version["extracted_text"], "")
            self.assertNotIn("ingest_preview_text", source["metadata"])
            self.assertNotIn("ingest_preview_truncated", source["metadata"])

    def test_ingest_storage_source_compile_handles_legacy_partial_source_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            service = self.import_backend_module("service")
            database = self.import_backend_module("database")
            database.ensure_schema(data_root)
            with database.connect(data_root) as db:
                db.execute("DROP INDEX idx_sources_external_ref")
                db.execute(
                    "CREATE UNIQUE INDEX idx_sources_external_ref ON sources(external_ref_id) WHERE status = 'active'"
                )

            status, result = service.handle_action(
                data_root,
                {
                    "action": "ingest_storage_source",
                    "title": "Drive renewal plan",
                    "memory_source": self.drive_memory_source(),
                    "preview_text": "Drive renewal plan says the renewal owner is Dana.",
                    "compile_after_ingest": True,
                },
            )

            self.assertEqual(status, 200)
            self.assertEqual(result["compiled"]["compiled_page"]["freshness"], "fresh")
            self.assertEqual(result["compiled"]["sources"][0]["external_ref_id"], result["external_ref"]["id"])

    def test_agent_drive_workflow_starts_in_memory_and_returns_storage_preview_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            storage_sources = self.import_backend_module("storage_sources")
            service = self.import_backend_module("service")
            memory_source = self.drive_memory_source(
                storage_file_id="file_drive_board_pack",
                drive_file_id="drive_board_pack",
                source_version="rev-board-7",
            )
            memory_source["title"] = "Board approval pack"
            memory_source["metadata"]["display_path"] = "/Drive/Board/Approval pack.md"
            drive_index_payload = {
                "status": "ready_for_memory",
                "provider": "google_drive",
                "connection_id": "drive_conn_acme",
                "drive_file_id": "drive_board_pack",
                "source_version": "rev-board-7",
                "preview_text": "Board approval pack says the deadline is June 15 and the owner is Dana.",
                "preview_truncated": False,
                "memory_source": memory_source,
            }

            miss_status, miss = service.handle_action(data_root, {"action": "context", "query": "June 15 approval deadline"})
            original_surface = storage_sources._storage_preview_surface
            try:
                storage_sources._storage_preview_surface = lambda _data_root, _request: (_ for _ in ()).throw(
                    AssertionError("drive_index preview_text should satisfy immediate Memory compile")
                )
                ingest_status, ingested = service.handle_action(
                    data_root,
                    {
                        "action": "ingest_storage_source",
                        "title": "Board approval pack",
                        "memory_source": drive_index_payload["memory_source"],
                        "preview_text": drive_index_payload["preview_text"],
                        "preview_truncated": drive_index_payload["preview_truncated"],
                        "source_version": drive_index_payload["source_version"],
                        "compile_after_ingest": True,
                    },
                )
                context_status, context = service.handle_action(data_root, {"action": "context", "query": "June 15 approval deadline"})
                wiki_status, wiki_result = service.handle_action(data_root, {"action": "wiki_query", "query": "June 15"})
            finally:
                storage_sources._storage_preview_surface = original_surface

            self.assertEqual(miss_status, 200)
            self.assertEqual(miss["items"], [])
            self.assertEqual(ingest_status, 200)
            self.assertTrue(ingested["compiled"]["citations"])
            citation = ingested["compiled"]["citations"][0]
            self.assertEqual(citation["source_version"], "rev-board-7")
            self.assertEqual(citation["storage_reference"]["deep_link"], "/app/storage/files/file_drive_board_pack")
            self.assertEqual(context_status, 200)
            self.assertEqual(wiki_status, 200)
            context_ref = context["items"][0]["storage_references"][0]
            wiki_ref = wiki_result["results"][0]["storage_references"][0]
            for storage_ref in (context_ref, wiki_ref, citation["storage_reference"]):
                self.assertEqual(storage_ref["provider"], "google_drive")
                self.assertEqual(storage_ref["workspace_relative_path"], "")
                self.assertEqual(storage_ref["stable_storage_file_id"], "file_drive_board_pack")
                self.assertEqual(storage_ref["connection_id"], "drive_conn_acme")
                self.assertEqual(storage_ref["drive_file_id"], "drive_board_pack")
                self.assertEqual(storage_ref["source_version"], "rev-board-7")
                self.assertEqual(storage_ref["preview_request"]["tool"], "storage_drive_preview")
                self.assertEqual(storage_ref["preview_request"]["arguments"]["stable_storage_file_id"], "file_drive_board_pack")
                self.assertEqual(storage_ref["export_request"]["tool"], "storage_drive_export")
                self.assertEqual(storage_ref["reference_resolve_request"]["tool"], "storage_reference_resolve")
                self.assertEqual(storage_ref["deep_link"], "/app/storage/files/file_drive_board_pack")

    def test_ingest_storage_source_attaches_existing_node_and_rejects_secret_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            node = self.run_backend(
                data_root,
                {"action": "remember", "title": "Existing Drive node", "body": "Existing context.", "type": "fact"},
            )["json"]["node"]

            attached = self.run_backend(
                data_root,
                {
                    "action": "ingest_storage_source",
                    "node_id": node["id"],
                    "memory_source": self.drive_memory_source(storage_file_id="file_drive_existing", drive_file_id="drive_existing"),
                    "preview_text": "Existing Drive node evidence.",
                },
            )
            rejected_source = self.drive_memory_source(storage_file_id="file_drive_secret", drive_file_id="drive_secret")
            rejected_source["metadata"]["refresh_token"] = "sensitive"
            rejected = self.run_backend(
                data_root,
                {
                    "action": "ingest_storage_source",
                    "memory_source": rejected_source,
                    "preview_text": "Should not be saved.",
                },
            )
            missing_version_source = self.drive_memory_source(storage_file_id="file_drive_no_version", drive_file_id="drive_no_version")
            missing_version_source["metadata"].pop("source_version")
            missing_version = self.run_backend(
                data_root,
                {
                    "action": "ingest_storage_source",
                    "memory_source": missing_version_source,
                    "preview_text": "Should not be saved.",
                },
            )

            self.assertEqual(attached["status_code"], 200)
            self.assertFalse(attached["json"]["node_created"])
            self.assertEqual(attached["json"]["external_ref"]["node_id"], node["id"])
            self.assertEqual(attached["json"]["external_ref"]["entity_id"], "file_drive_existing")
            self.assertEqual(rejected["status_code"], 400)
            self.assertIn("secret fields", rejected["json"]["detail"])
            self.assertEqual(missing_version["status_code"], 400)
            self.assertIn("source_version", missing_version["json"]["detail"])

    def test_ingest_storage_source_keeps_same_drive_file_on_multiple_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            service = self.import_backend_module("service")
            database = self.import_backend_module("database")
            storage_file_id = "file_drive_shared"
            memory_source = self.drive_memory_source(storage_file_id=storage_file_id, drive_file_id="drive_shared")
            first_node = service.handle_action(data_root, {"action": "remember", "title": "First node", "body": "First"})[1]["node"]
            second_node = service.handle_action(data_root, {"action": "remember", "title": "Second node", "body": "Second"})[1]["node"]

            first_status, first = service.handle_action(
                data_root,
                {
                    "action": "ingest_storage_source",
                    "node_id": first_node["id"],
                    "memory_source": memory_source,
                    "preview_text": "Shared Drive evidence.",
                    "compile_after_ingest": True,
                },
            )
            second_status, second = service.handle_action(
                data_root,
                {
                    "action": "ingest_storage_source",
                    "node_id": second_node["id"],
                    "memory_source": memory_source,
                    "preview_text": "Shared Drive evidence.",
                    "compile_after_ingest": True,
                },
            )
            stale_status, stale = service.handle_action(
                data_root,
                {
                    "action": "apply_storage_staleness",
                    "memory_staleness": {
                        "owning_app_id": "storage",
                        "entity_type": "file",
                        "entity_id": storage_file_id,
                        "reason": "google_drive_change",
                        "connection_id": "drive_conn_acme",
                        "drive_file_id": "drive_changed",
                        "source_version": "rev-2",
                        "indexed_source_version": "rev-1",
                    },
                },
            )

            with database.connect(data_root) as db:
                refs = [
                    database.row_payload(row) or {}
                    for row in db.execute("SELECT * FROM external_refs WHERE entity_id = ? ORDER BY node_id", (storage_file_id,))
                ]

            self.assertEqual(first_status, 200)
            self.assertEqual(second_status, 200)
            self.assertTrue(first["external_ref_created"])
            self.assertTrue(second["external_ref_created"])
            self.assertEqual({ref["node_id"] for ref in refs}, {first_node["id"], second_node["id"]})
            self.assertEqual(stale_status, 200)
            self.assertEqual(len(stale["impacted_nodes"]), 2)

    def test_ingest_storage_source_rejects_nested_secret_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            source = self.drive_memory_source(storage_file_id="file_drive_nested_secret", drive_file_id="drive_nested_secret")
            source["metadata"]["oauth"] = {"accessToken": "sensitive"}

            rejected = self.run_backend(
                data_root,
                {
                    "action": "ingest_storage_source",
                    "memory_source": source,
                    "preview_text": "Should not be saved.",
                },
            )

            self.assertEqual(rejected["status_code"], 400)
            self.assertIn("oauth.accessToken", rejected["json"]["detail"])

    def test_ingest_storage_source_compile_failure_does_not_create_fresh_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            storage_sources = self.import_backend_module("storage_sources")
            service = self.import_backend_module("service")
            database = self.import_backend_module("database")
            errors = self.import_backend_module("errors")
            original_surface = storage_sources._storage_preview_surface
            try:
                storage_sources._storage_preview_surface = lambda _data_root, _request: (_ for _ in ()).throw(
                    errors.MemoryValidationError("Storage preview failed.")
                )
                with self.assertRaises(errors.MemoryValidationError):
                    service.handle_action(
                        data_root,
                        {
                            "action": "ingest_storage_source",
                            "title": "Preview failure",
                            "memory_source": self.drive_memory_source(storage_file_id="file_drive_failure", drive_file_id="drive_failure"),
                            "compile_after_ingest": True,
                        },
                    )
            finally:
                storage_sources._storage_preview_surface = original_surface

            with database.connect(data_root) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) AS count FROM external_refs").fetchone()["count"], 0)
                self.assertEqual(db.execute("SELECT COUNT(*) AS count FROM sources").fetchone()["count"], 0)
                self.assertEqual(db.execute("SELECT COUNT(*) AS count FROM source_versions").fetchone()["count"], 0)
                self.assertEqual(db.execute("SELECT COUNT(*) AS count FROM wiki_pages WHERE freshness = 'fresh'").fetchone()["count"], 0)

    def test_platform_storage_preview_uses_mcp_argument_flags(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            storage_sources = self.import_backend_module("storage_sources")
            calls: list[list[str]] = []
            original_run = storage_sources.subprocess.run
            original_which = storage_sources.shutil.which

            class Completed:
                returncode = 0
                stdout = json.dumps({"status_code": 200, "preview_text": "Drive preview text."})

            def fake_run(args: list[str], **_kwargs: object) -> Completed:
                calls.append(args)
                return Completed()

            try:
                storage_sources.shutil.which = lambda _name: "/usr/bin/maverick"
                storage_sources.subprocess.run = fake_run
                result = storage_sources.default_storage_preview_surface(
                    data_root,
                    {
                        "connection_id": "drive_conn_acme",
                        "drive_file_id": "drive_plan",
                        "stable_storage_file_id": "file_drive_plan",
                        "max_chars": 20000,
                        "max_bytes": 1024,
                    },
                )
            finally:
                storage_sources.subprocess.run = original_run
                storage_sources.shutil.which = original_which

            self.assertEqual(result["preview_text"], "Drive preview text.")
            self.assertEqual(calls[0][:7], ["maverick", "app", "storage", "mcp", "call", "storage_drive_preview", "--json"])
            self.assertNotIn("--arguments", calls[0])
            self.assertIn("--stable-storage-file-id", calls[0])
            self.assertIn("file_drive_plan", calls[0])
            self.assertIn("--connection-id", calls[0])
            self.assertIn("--drive-file-id", calls[0])
            self.assertIn("--max-chars", calls[0])

    def test_remote_storage_ingestion_uses_storage_preview_and_cites_source_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace_root = Path(temp)
            data_root = workspace_root / "data" / "memory"
            node = self.run_backend(
                data_root,
                {
                    "action": "remember",
                    "title": "Drive renewal",
                    "body": "Remote agreement says renewal owner is Dana.",
                    "type": "fact",
                },
            )["json"]["node"]
            self.run_backend(
                data_root,
                {
                    "action": "attach_file",
                    "node_id": node["id"],
                    "owning_app_id": "storage",
                    "entity_type": "file",
                    "entity_id": "file_drive_renewal",
                    "title": "Renewal agreement",
                    "metadata": {
                        "provider": "google_drive",
                        "connection_id": "drive_conn_acme",
                        "drive_file_id": "drive_file_renewal",
                        "source_version": "rev-1",
                        "display_path": "/Agreements/Renewal.md",
                    },
                },
            )

            sources = self.import_backend_module("sources")
            storage_sources = self.import_backend_module("storage_sources")
            wiki = self.import_backend_module("wiki")
            calls: list[dict] = []

            def fake_storage_preview(data_root_arg: Path, request: dict) -> dict:
                calls.append(request)
                self.assertEqual(data_root_arg, data_root)
                self.assertNotIn("workspace_relative_path", request)
                self.assertNotIn("token", request)
                self.assertNotIn("refresh_token", request)
                return {
                    "file": {
                        "id": "file_drive_renewal",
                        "etag_or_version": "rev-2",
                        "display_path": "/Agreements/Renewal.md",
                    },
                    "preview_text": "Remote agreement says renewal owner is Dana.",
                    "truncated": False,
                }

            original_surface = storage_sources._storage_preview_surface
            original_file_hash = sources.file_hash
            try:
                storage_sources._storage_preview_surface = fake_storage_preview
                sources.file_hash = lambda path: (_ for _ in ()).throw(AssertionError("Drive source used filesystem hash"))
                compiled = wiki.compile_node(data_root, {"node_id": node["id"]})
            finally:
                storage_sources._storage_preview_surface = original_surface
                sources.file_hash = original_file_hash

            self.assertEqual(calls[0]["action"], "drive_preview")
            self.assertEqual(calls[0]["provider"], "google_drive")
            self.assertEqual(calls[0]["stable_storage_file_id"], "file_drive_renewal")
            self.assertEqual(calls[0]["connection_id"], "drive_conn_acme")
            self.assertEqual(calls[0]["drive_file_id"], "drive_file_renewal")
            self.assertEqual(compiled["compiled_page"]["freshness"], "fresh")
            self.assertTrue(compiled["citations"])
            citation = compiled["citations"][0]
            self.assertTrue(citation["source_version_id"].startswith("srcv_"))
            self.assertEqual(citation["metadata"]["source_version"], "rev-2")
            self.assertEqual(citation["locator"], "/Agreements/Renewal.md")

    def test_remote_storage_staleness_marks_compiled_wiki_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            node = self.run_backend(
                data_root,
                {"action": "remember", "title": "Stale Drive source", "body": "Drive indexed fact.", "type": "fact"},
            )["json"]["node"]
            self.run_backend(
                data_root,
                {
                    "action": "attach_file",
                    "node_id": node["id"],
                    "owning_app_id": "storage",
                    "entity_type": "file",
                    "entity_id": "file_drive_stale",
                    "metadata": {
                        "provider": "google_drive",
                        "connection_id": "drive_conn_acme",
                        "drive_file_id": "drive_file_stale",
                        "source_version": "rev-1",
                        "display_path": "/Drive/Stale.md",
                        "sync_state": {"status": "stale", "error": "google_drive_change"},
                    },
                },
            )

            storage_sources = self.import_backend_module("storage_sources")
            wiki = self.import_backend_module("wiki")
            original_surface = storage_sources._storage_preview_surface
            try:
                storage_sources._storage_preview_surface = lambda _data_root, _request: {
                    "file": {"etag_or_version": "rev-1", "display_path": "/Drive/Stale.md"},
                    "preview_text": "Drive indexed fact.",
                }
                compiled = wiki.compile_node(data_root, {"node_id": node["id"]})
            finally:
                storage_sources._storage_preview_surface = original_surface

            self.assertEqual(compiled["compiled_page"]["freshness"], "stale")
            self.assertTrue(any(finding["finding_type"] == "stale_page" for finding in compiled["lint_findings"]))

    def test_apply_storage_staleness_updates_refs_and_marks_impacted_nodes_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            service = self.import_backend_module("service")
            storage_sources = self.import_backend_module("storage_sources")
            database = self.import_backend_module("database")
            storage_file_id = "file_drive_changed"
            memory_source = self.drive_memory_source(storage_file_id=storage_file_id, drive_file_id="drive_changed")

            first_status, first = service.handle_action(
                data_root,
                {
                    "action": "ingest_storage_source",
                    "title": "Changed Drive document",
                    "memory_source": memory_source,
                    "preview_text": "Drive indexed fact for changed file.",
                    "compile_after_ingest": True,
                },
            )
            second_node = service.handle_action(
                data_root,
                {"action": "remember", "title": "Second Drive node", "body": "Drive indexed fact for changed file.", "type": "fact"},
            )[1]["node"]
            service.handle_action(
                data_root,
                {
                    "action": "attach_file",
                    "node_id": second_node["id"],
                    "owning_app_id": "storage",
                    "entity_type": "file",
                    "entity_id": storage_file_id,
                    "metadata": memory_source["metadata"],
                },
            )

            original_surface = storage_sources._storage_preview_surface
            try:
                storage_sources._storage_preview_surface = lambda _data_root, _request: {
                    "file": {"etag_or_version": "rev-1", "display_path": "/Drive/Plans/Plan.md"},
                    "preview_text": "Drive indexed fact for changed file.",
                }
                service.handle_action(data_root, {"action": "compile", "node_id": second_node["id"]})
            finally:
                storage_sources._storage_preview_surface = original_surface

            status, applied = service.handle_action(
                data_root,
                {
                    "action": "apply_storage_staleness",
                    "memory_staleness": {
                        "owning_app_id": "storage",
                        "entity_type": "file",
                        "entity_id": storage_file_id,
                        "reason": "google_drive_change",
                        "connection_id": "drive_conn_acme",
                        "drive_file_id": "drive_changed",
                        "source_version": "rev-2",
                        "indexed_source_version": "rev-1",
                    },
                },
            )
            first_inspect = service.handle_action(data_root, {"action": "inspect", "node_id": first["node"]["id"]})[1]
            second_inspect = service.handle_action(data_root, {"action": "inspect", "node_id": second_node["id"]})[1]

            with database.connect(data_root) as db:
                refs = [
                    database.row_payload(row) or {}
                    for row in db.execute("SELECT * FROM external_refs WHERE entity_id = ? ORDER BY node_id", (storage_file_id,))
                ]
                stale_claim_count = db.execute(
                    "SELECT COUNT(*) AS count FROM claims WHERE stale = 1 AND node_id IN (?, ?)",
                    (first["node"]["id"], second_node["id"]),
                ).fetchone()["count"]

            self.assertEqual(first_status, 200)
            self.assertEqual(status, 200)
            self.assertEqual(applied["status"], "applied")
            self.assertEqual(applied["storage_identity"]["entity_id"], storage_file_id)
            self.assertEqual(len(applied["impacted_nodes"]), 2)
            self.assertEqual(applied["reindex_suggestion"]["mcp_tool"], "storage_drive_index")
            self.assertEqual(applied["reindex_suggestion"]["arguments"]["stable_storage_file_id"], storage_file_id)
            self.assertTrue(all(node["compiled_wiki_stale"] for node in applied["impacted_nodes"]))
            self.assertEqual(len(refs), 2)
            self.assertTrue(all(ref["metadata"]["stale"] for ref in refs))
            self.assertTrue(all(ref["metadata"]["sync_state"]["status"] == "stale" for ref in refs))
            self.assertTrue(all(ref["metadata"]["staleness"]["reason"] == "google_drive_change" for ref in refs))
            self.assertTrue(all(ref["metadata"]["staleness"]["source_version"] == "rev-2" for ref in refs))
            self.assertEqual(applied["reindex_suggestion"]["arguments"]["connection_id"], "drive_conn_acme")
            self.assertEqual(applied["reindex_suggestion"]["arguments"]["drive_file_id"], "drive_changed")
            self.assertGreaterEqual(stale_claim_count, 2)
            self.assertEqual(first_inspect["node"]["compiled_page"]["freshness"], "stale")
            self.assertEqual(second_inspect["node"]["compiled_page"]["freshness"], "stale")

    def test_reingest_storage_source_clears_staleness_and_restores_fresh_compile(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            service = self.import_backend_module("service")
            database = self.import_backend_module("database")
            storage_file_id = "file_drive_reindexed"
            first_source = self.drive_memory_source(storage_file_id=storage_file_id, drive_file_id="drive_reindexed", source_version="rev-1")

            first_status, first = service.handle_action(
                data_root,
                {
                    "action": "ingest_storage_source",
                    "title": "Reindexed Drive document",
                    "memory_source": first_source,
                    "preview_text": "Drive fact before change.",
                    "compile_after_ingest": True,
                },
            )
            stale_status, stale = service.handle_action(
                data_root,
                {
                    "action": "apply_storage_staleness",
                    "memory_staleness": {
                        "owning_app_id": "storage",
                        "entity_type": "file",
                        "entity_id": storage_file_id,
                        "reason": "google_drive_change",
                    },
                },
            )
            second_source = self.drive_memory_source(storage_file_id=storage_file_id, drive_file_id="drive_reindexed", source_version="rev-2")
            second_status, second = service.handle_action(
                data_root,
                {
                    "action": "ingest_storage_source",
                    "title": "Reindexed Drive document",
                    "memory_source": second_source,
                    "preview_text": "Drive fact after change.",
                    "source_version": "rev-2",
                    "compile_after_ingest": True,
                },
            )

            with database.connect(data_root) as db:
                ref = database.row_payload(db.execute("SELECT * FROM external_refs WHERE entity_id = ?", (storage_file_id,)).fetchone()) or {}

            self.assertEqual(first_status, 200)
            self.assertEqual(first["compiled"]["compiled_page"]["freshness"], "fresh")
            self.assertEqual(stale_status, 200)
            self.assertEqual(stale["status"], "applied")
            self.assertEqual(second_status, 200)
            self.assertEqual(second["compiled"]["compiled_page"]["freshness"], "fresh")
            self.assertFalse(second["external_ref"]["metadata"].get("stale", False))
            self.assertNotIn("staleness", second["external_ref"]["metadata"])
            self.assertNotIn("sync_state", second["external_ref"]["metadata"])
            self.assertFalse(ref["metadata"].get("stale", False))

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

    def test_mcp_tool_arguments_cannot_override_declared_tool_action(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            node = run_json_entrypoint(
                MEMORY_ROOT / "backend" / "app_backend.py",
                payload={"data_root": str(data_root), "body": {"action": "remember", "title": "Protected node", "body": "Keep me."}},
                cwd=MEMORY_ROOT,
            )["json"]["node"]

            malicious = run_json_entrypoint(
                MEMORY_ROOT / "mcp" / "server.py",
                payload={
                    "workspace_id": "default",
                    "app_id": "memory",
                    "data_root": str(data_root),
                    "tool_name": "memory_lint",
                    "arguments": {"action": "delete_node", "node_id": node["id"]},
                },
                cwd=MEMORY_ROOT,
            )
            inspect = run_json_entrypoint(
                MEMORY_ROOT / "backend" / "app_backend.py",
                payload={"data_root": str(data_root), "body": {"action": "inspect", "node_id": node["id"]}},
                cwd=MEMORY_ROOT,
            )

            self.assertEqual(malicious["status_code"], 400)
            self.assertEqual(malicious["error"], "validation_error")
            self.assertEqual(inspect["status_code"], 200)
            self.assertEqual(inspect["json"]["node"]["status"], "active")

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
