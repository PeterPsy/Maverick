"""Tests for the Memory app."""

from __future__ import annotations

from contextlib import redirect_stdout
from base64 import b64encode
from hashlib import sha256
from io import StringIO
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
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
        self.assertIn("memory_ingest_source", parsed.contract.capabilities.mcp_tools)
        self.assertIn("memory_ingest_storage_source", parsed.contract.capabilities.mcp_tools)
        self.assertIn("memory_apply_storage_staleness", parsed.contract.capabilities.mcp_tools)
        self.assertIn("memory_source_query", parsed.contract.capabilities.mcp_tools)
        self.assertIn("memory_fetch_chunks", parsed.contract.capabilities.mcp_tools)
        self.assertIn("memory_inspect_source", parsed.contract.capabilities.mcp_tools)
        self.assertIn("memory_jobs", parsed.contract.capabilities.mcp_tools)
        self.assertIn("memory_reference_manifest", parsed.contract.capabilities.mcp_tools)
        self.assertIn("memory_set_view_filter", parsed.contract.capabilities.mcp_tools)
        self.assertEqual(parsed.contract.capabilities.cli_commands, ["memory"])
        self.assertEqual(parsed.contract.storage.storage_kind, "sqlite+files")
        self.assertEqual(parsed.contract.storage.data_schema_version, "3")
        self.assertIn("data/memory/content", parsed.contract.storage.primary_paths)
        required_interfaces = {requirement.alias: requirement for requirement in parsed.contract.requires}
        self.assertEqual(required_interfaces["storage-file-catalog"].interface, "file.catalog")
        self.assertTrue(required_interfaces["storage-file-catalog"].required)
        self.assertEqual(required_interfaces["storage-file-content-read"].interface, "file.content.read")
        self.assertTrue(required_interfaces["storage-file-content-read"].required)
        self.assertEqual(required_interfaces["storage-google-drive"].interface, "file.provider.google-drive")
        self.assertFalse(required_interfaces["storage-google-drive"].required)
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
        jobs_schema = mcp_descriptor["tools"]["memory_jobs"]["input_schema"]
        self.assertEqual(
            jobs_schema["properties"]["operation"]["enum"],
            ["list", "enqueue", "claim", "complete", "fail", "cancel", "run_next", "run_until_idle"],
        )
        self.assertIn("lease_token", jobs_schema["properties"])
        self.assertIn("max_jobs", jobs_schema["properties"])
        self.assertIn("requires_storage_reindex", jobs_schema["properties"]["job_type"]["enum"])
        self.assertEqual(
            mcp_descriptor["tools"]["memory_ingest_source"]["input_schema"]["properties"]["adapter_id"]["enum"],
            ["inline_markdown", "storage_file", "remote_storage_file", "app_entity"],
        )
        self.assertIn(
            {"required": ["adapter_id", "owning_app_id", "entity_type", "entity_id"]},
            mcp_descriptor["tools"]["memory_ingest_source"]["input_schema"]["anyOf"],
        )
        self.assertEqual(
            cli_descriptor["commands"]["memory"]["argument_schema"]["properties"]["adapter_id"]["enum"],
            ["inline_markdown", "storage_file", "remote_storage_file", "app_entity"],
        )
        self.assertIn(
            "Workspace Storage path",
            cli_descriptor["commands"]["memory"]["argument_schema"]["properties"]["workspace_relative_path"]["description"],
        )
        self.assertIn(
            "Stable Storage file id",
            cli_descriptor["commands"]["memory"]["argument_schema"]["properties"]["file_id"]["description"],
        )
        self.assert_no_duplicate_json_keys(MEMORY_ROOT / "cli" / "command_schemas.json")

    def test_memory_skill_documents_drive_ingest_workflow(self) -> None:
        skill = (MEMORY_ROOT / "skills" / "memory-ops" / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("storage_drive_index", skill)
        self.assertIn("adapter-id remote_storage_file", skill)
        self.assertIn("adapter-id app_entity", skill)
        self.assertIn("memory_ingest_storage_source", skill)
        self.assertIn("storage_drive_mark_indexed", skill)
        self.assertIn("memory_apply_storage_staleness", skill)
        self.assertIn("Memory never scans Drive itself", skill)

    def assert_no_duplicate_json_keys(self, path: Path) -> None:
        def no_duplicates(pairs):
            seen = set()
            payload = {}
            for key, value in pairs:
                self.assertNotIn(key, seen, f"Duplicate JSON key `{key}` in {path}")
                seen.add(key)
                payload[key] = value
            return payload

        json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=no_duplicates)

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
            self.assertTrue((data_root / "content").is_dir())
            health = run_json_entrypoint(MEMORY_ROOT / "hooks" / "health_check.py", payload=payload, cwd=MEMORY_ROOT)
            self.assertEqual(health["schema_version"], "3")

    def test_schema_v2_database_migrates_to_v3_source_chunk_foundation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            data_root.mkdir(parents=True, exist_ok=True)
            db_file = data_root / "memory.sqlite"
            with sqlite3.connect(db_file) as db:
                db.execute("CREATE TABLE schema_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                db.execute("INSERT INTO schema_metadata(key, value) VALUES ('schema_version', '2')")
                db.execute(
                    """
                    CREATE TABLE source_versions (
                      id TEXT PRIMARY KEY,
                      source_id TEXT NOT NULL,
                      version_hash TEXT NOT NULL,
                      extracted_text TEXT NOT NULL DEFAULT '',
                      extracted_ref TEXT NOT NULL DEFAULT '',
                      observed_at TEXT NOT NULL,
                      created_at TEXT NOT NULL,
                      metadata_json TEXT NOT NULL DEFAULT '{}'
                    )
                    """
                )
                db.execute(
                    """
                    INSERT INTO source_versions(id, source_id, version_hash, extracted_text, extracted_ref, observed_at, created_at)
                    VALUES (
                      'srcv_old',
                      'src_old',
                      'hash-old',
                      'Legacy source text says migration evidence is preserved.',
                      'legacy://source',
                      '2026-01-01T00:00:00+00:00',
                      '2026-01-01T00:00:00+00:00'
                    )
                    """
                )
                db.execute(
                    """
                    CREATE TABLE citations (
                      id TEXT PRIMARY KEY,
                      claim_id TEXT NOT NULL,
                      source_id TEXT,
                      source_version_id TEXT,
                      external_ref_id TEXT,
                      locator TEXT NOT NULL DEFAULT '',
                      quote TEXT NOT NULL DEFAULT '',
                      created_at TEXT NOT NULL,
                      metadata_json TEXT NOT NULL DEFAULT '{}'
                    )
                    """
                )
                db.execute(
                    """
                    INSERT INTO citations(id, claim_id, source_version_id, locator, quote, created_at)
                    VALUES ('cite_old', 'claim_old', 'srcv_old', 'old locator', 'old quote', '2026-01-01T00:00:00+00:00')
                    """
                )

            migrated = run_json_entrypoint(MEMORY_ROOT / "hooks" / "migrate.py", payload={"data_root": str(data_root)}, cwd=MEMORY_ROOT)
            database = self.import_backend_module("database")

            with database.connect(data_root) as db:
                schema_version = db.execute("SELECT value FROM schema_metadata WHERE key = 'schema_version'").fetchone()["value"]
                source_version_columns = {row["name"] for row in db.execute("PRAGMA table_info(source_versions)")}
                citation_columns = {row["name"] for row in db.execute("PRAGMA table_info(citations)")}
                ingest_job_columns = {row["name"] for row in db.execute("PRAGMA table_info(ingest_jobs)")}
                self.assertEqual(db.execute("SELECT COUNT(*) AS count FROM source_documents").fetchone()["count"], 1)
                self.assertEqual(db.execute("SELECT COUNT(*) AS count FROM source_chunks").fetchone()["count"], 1)
                self.assertEqual(db.execute("SELECT COUNT(*) AS count FROM source_chunk_fts").fetchone()["count"], 1)
                self.assertEqual(db.execute("SELECT COUNT(*) AS count FROM ingest_jobs").fetchone()["count"], 0)
                migrated_version = database.row_payload(db.execute("SELECT * FROM source_versions WHERE id = 'srcv_old'").fetchone()) or {}
                migrated_citation = database.row_payload(db.execute("SELECT * FROM citations WHERE id = 'cite_old'").fetchone()) or {}
                migrated_document = database.row_payload(db.execute("SELECT * FROM source_documents").fetchone()) or {}
                migrated_chunk = database.row_payload(db.execute("SELECT * FROM source_chunks").fetchone()) or {}

            self.assertEqual(migrated["schema_version"], "3")
            self.assertEqual(schema_version, "3")
            self.assertIn("source_document_id", source_version_columns)
            self.assertIn("body_path", source_version_columns)
            self.assertIn("body_sha256", source_version_columns)
            self.assertIn("hash_kind", source_version_columns)
            self.assertIn("extraction_status", source_version_columns)
            self.assertIn("source_chunk_id", citation_columns)
            self.assertIn("quote_sha256", citation_columns)
            self.assertIn("lease_token", ingest_job_columns)
            self.assertIn("node_id", ingest_job_columns)
            self.assertIn("source_document_id", ingest_job_columns)
            self.assertIn("source_version_id", ingest_job_columns)
            self.assertEqual(migrated_version["version_hash"], "hash-old")
            self.assertEqual(migrated_version["source_document_id"], migrated_document["id"])
            self.assertEqual(migrated_document["source_key"], "legacy:src_old")
            self.assertTrue(migrated_version["body_path"].startswith("content/sources/"))
            self.assertTrue(migrated_version["body_sha256"])
            self.assertEqual(migrated_version["hash_kind"], "canonical_body")
            self.assertEqual(migrated_version["extraction_status"], "available")
            self.assertEqual(migrated_chunk["source_version_id"], "srcv_old")
            self.assertTrue(migrated_chunk["body_path"].startswith("content/chunks/"))
            self.assertEqual(migrated_chunk["locator"], "legacy://source")
            self.assertEqual(migrated_chunk["locator_kind"], "migration_extracted_text")
            self.assertEqual(migrated_citation["locator"], "old locator")
            self.assertEqual(migrated_citation["quote_sha256"], "")

    def test_schema_v2_remote_storage_source_migrates_to_remote_storage_document(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            data_root.mkdir(parents=True, exist_ok=True)
            db_file = data_root / "memory.sqlite"
            with sqlite3.connect(db_file) as db:
                db.execute("CREATE TABLE schema_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                db.execute("INSERT INTO schema_metadata(key, value) VALUES ('schema_version', '2')")
                db.execute(
                    """
                    CREATE TABLE sources (
                      id TEXT PRIMARY KEY,
                      source_kind TEXT NOT NULL,
                      external_ref_id TEXT,
                      owning_app_id TEXT NOT NULL DEFAULT '',
                      entity_type TEXT NOT NULL DEFAULT '',
                      entity_id TEXT NOT NULL DEFAULT '',
                      file_id TEXT NOT NULL DEFAULT '',
                      workspace_relative_path TEXT NOT NULL DEFAULT '',
                      uri TEXT NOT NULL DEFAULT '',
                      title TEXT NOT NULL DEFAULT '',
                      content_hash TEXT NOT NULL DEFAULT '',
                      status TEXT NOT NULL DEFAULT 'active',
                      created_at TEXT NOT NULL,
                      updated_at TEXT NOT NULL,
                      metadata_json TEXT NOT NULL DEFAULT '{}'
                    )
                    """
                )
                db.execute(
                    """
                    INSERT INTO sources(
                      id, source_kind, owning_app_id, entity_type, entity_id, file_id,
                      workspace_relative_path, title, content_hash, created_at, updated_at, metadata_json
                    )
                    VALUES (
                      'src_drive_legacy',
                      'remote_storage_file',
                      'storage',
                      'file',
                      'file_drive_legacy',
                      'file_drive_legacy',
                      '',
                      'Legacy Drive plan',
                      'hash-drive-old',
                      '2026-01-01T00:00:00+00:00',
                      '2026-01-01T00:00:00+00:00',
                      '{"provider":"google_drive","drive_file_id":"drive_legacy","source_version":"rev-old"}'
                    )
                    """
                )
                db.execute(
                    """
                    CREATE TABLE source_versions (
                      id TEXT PRIMARY KEY,
                      source_id TEXT NOT NULL,
                      version_hash TEXT NOT NULL,
                      extracted_text TEXT NOT NULL DEFAULT '',
                      extracted_ref TEXT NOT NULL DEFAULT '',
                      observed_at TEXT NOT NULL,
                      created_at TEXT NOT NULL,
                      metadata_json TEXT NOT NULL DEFAULT '{}'
                    )
                    """
                )
                db.execute(
                    """
                    INSERT INTO source_versions(id, source_id, version_hash, extracted_text, extracted_ref, observed_at, created_at)
                    VALUES (
                      'srcv_drive_legacy',
                      'src_drive_legacy',
                      'hash-drive-old',
                      'Legacy Drive plan says the owner is Dana.',
                      '/Drive/Plans/Legacy.md',
                      '2026-01-01T00:00:00+00:00',
                      '2026-01-01T00:00:00+00:00'
                    )
                    """
                )

            migrated = run_json_entrypoint(MEMORY_ROOT / "hooks" / "migrate.py", payload={"data_root": str(data_root)}, cwd=MEMORY_ROOT)
            service = self.import_backend_module("service")
            database = self.import_backend_module("database")
            status, ingested = service.handle_action(
                data_root,
                {
                    "action": "ingest_storage_source",
                    "title": "Legacy Drive plan",
                    "memory_source": self.drive_memory_source(
                        storage_file_id="file_drive_legacy",
                        drive_file_id="drive_legacy",
                        source_version="rev-new",
                    ),
                    "preview_text": "Legacy Drive plan says the owner is Dana and the reviewer is Lee.",
                    "compile_after_ingest": True,
                },
            )

            with database.connect(data_root) as db:
                document_count = db.execute("SELECT COUNT(*) AS count FROM source_documents").fetchone()["count"]
                document = database.row_payload(db.execute("SELECT * FROM source_documents").fetchone()) or {}
                versions = [
                    database.row_payload(row) or {}
                    for row in db.execute("SELECT * FROM source_versions ORDER BY created_at")
                ]

            self.assertEqual(migrated["schema_version"], "3")
            self.assertEqual(status, 200)
            self.assertEqual(document_count, 1)
            self.assertEqual(document["adapter_id"], "remote_storage_file")
            self.assertEqual(document["source_key"], "remote_storage_file:file_drive_legacy")
            self.assertEqual(document["owning_app_id"], "storage")
            self.assertEqual(document["entity_type"], "file")
            self.assertEqual(document["entity_id"], "file_drive_legacy")
            self.assertEqual(document["workspace_relative_path"], "")
            self.assertEqual(ingested["storage_identity"]["entity_id"], "file_drive_legacy")
            self.assertEqual({version["source_document_id"] for version in versions}, {document["id"]})

    def test_schema_current_shape_requires_v3_source_tables_and_indexes(self) -> None:
        database = self.import_backend_module("database")

        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            database.ensure_schema(data_root)
            self.assertTrue(database.schema_is_current(data_root))

            with database.connect(data_root) as db:
                db.execute("DROP INDEX idx_source_chunks_hash")
                db.commit()
            self.assertFalse(database.schema_is_current(data_root))

            database.ensure_schema(data_root)
            self.assertTrue(database.schema_is_current(data_root))

            with database.connect(data_root) as db:
                db.execute("PRAGMA foreign_keys = OFF")
                db.execute("DROP TABLE source_chunks")
                db.commit()
            self.assertFalse(database.schema_is_current(data_root))

            database.ensure_schema(data_root)
            with database.connect(data_root) as db:
                source_chunk_columns = {row["name"] for row in db.execute("PRAGMA table_info(source_chunks)")}
                source_chunk_indexes = {row["name"] for row in db.execute("PRAGMA index_list(source_chunks)")}
                source_chunk_fts_columns = {row["name"] for row in db.execute("PRAGMA table_info(source_chunk_fts)")}

            self.assertTrue(database.schema_is_current(data_root))
            self.assertIn("source_version_id", source_chunk_columns)
            self.assertIn("body_sha256", source_chunk_columns)
            self.assertIn("idx_source_chunks_version_index", source_chunk_indexes)
            self.assertIn("idx_source_chunks_hash", source_chunk_indexes)
            self.assertIn("chunk_id", source_chunk_fts_columns)
            self.assertIn("body_text", source_chunk_fts_columns)

    def test_content_store_writes_relative_verified_immutable_bodies(self) -> None:
        content_store = self.import_backend_module("content_store")

        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            first = content_store.write_body(
                data_root,
                kind="sources",
                body_markdown="Evidence body\r\nwith CRLF",
                metadata={"source_version_id": "srcv_1"},
            )
            second = content_store.write_body(
                data_root,
                kind="sources",
                body_markdown="Evidence body\nwith CRLF\n",
                metadata={"ignored": "metadata is not authoritative"},
            )

            self.assertEqual(first, second)
            self.assertFalse(Path(first.relative_path).is_absolute())
            self.assertTrue(first.relative_path.startswith("content/sources/"))
            self.assertEqual(first.body_sha256, content_store.body_hash("Evidence body\nwith CRLF\n"))
            self.assertEqual(content_store.read_body(data_root, relative_path=first.relative_path), "Evidence body\nwith CRLF\n")
            stored_text = (data_root / first.relative_path).read_text(encoding="utf-8")
            self.assertTrue(stored_text.startswith("---\n"))
            self.assertIn('"source_version_id": "srcv_1"', stored_text)

    def test_content_store_rejects_unsafe_paths_and_hash_mismatch(self) -> None:
        content_store = self.import_backend_module("content_store")

        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            record = content_store.write_body(data_root, kind="chunks", body_markdown="Chunk evidence.")

            with self.assertRaisesRegex(ValueError, "relative"):
                content_store.read_body(data_root, relative_path=str((data_root / record.relative_path).resolve()))
            with self.assertRaisesRegex(ValueError, "traversal"):
                content_store.read_body(data_root, relative_path="content/chunks/aa/../../escape.md")

            (data_root / record.relative_path).write_text("---\n{}\n---\nTampered evidence.\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                content_store.read_body(data_root, relative_path=record.relative_path, expected_sha256=record.body_sha256)

    def test_ingest_jobs_dedupe_claim_retry_and_complete_with_lease(self) -> None:
        service = self.import_backend_module("service")

        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            status, first = service.handle_action(
                data_root,
                {
                    "action": "jobs_enqueue",
                    "job_type": "compile_node",
                    "dedupe_key": "compile:node_demo",
                    "payload": {"node_id": "node_demo"},
                },
            )
            second_status, second = service.handle_action(
                data_root,
                {
                    "action": "jobs_enqueue",
                    "job_type": "compile_node",
                    "dedupe_key": "compile:node_demo",
                    "payload": {"node_id": "node_demo", "reason": "updated"},
                },
            )
            claim_status, claimed = service.handle_action(data_root, {"action": "jobs_claim", "job_types": ["compile_node"], "lease_seconds": 30})
            job = claimed["job"]

            self.assertEqual(status, 200)
            self.assertEqual(second_status, 200)
            self.assertTrue(first["job"]["enqueued"])
            self.assertFalse(second["job"]["enqueued"])
            self.assertEqual(first["job"]["id"], second["job"]["id"])
            self.assertEqual(claim_status, 200)
            self.assertEqual(job["status"], "running")
            self.assertEqual(job["attempt_count"], 1)
            self.assertTrue(job["lease_token"].startswith("lease_"))
            running_duplicate_status, running_duplicate = service.handle_action(
                data_root,
                {
                    "action": "jobs_enqueue",
                    "job_type": "compile_node",
                    "dedupe_key": "compile:node_demo",
                    "payload": {"node_id": "node_demo", "reason": "must_not_replace_running_payload"},
                },
            )
            self.assertEqual(running_duplicate_status, 200)
            self.assertFalse(running_duplicate["job"]["enqueued"])
            self.assertEqual(running_duplicate["job"]["status"], "running")
            self.assertEqual(running_duplicate["job"]["payload"], {"node_id": "node_demo", "reason": "updated"})
            with self.assertRaisesRegex(Exception, "running job lease"):
                service.handle_action(data_root, {"action": "jobs_complete", "job_id": job["id"], "lease_token": "wrong"})

            fail_status, failed = service.handle_action(
                data_root,
                {"action": "jobs_fail", "job_id": job["id"], "lease_token": job["lease_token"], "error": "preview unavailable"},
            )
            self.assertEqual(fail_status, 200)
            self.assertEqual(failed["job"]["status"], "ready")
            self.assertEqual(failed["job"]["last_error"], "preview unavailable")

            service.handle_action(
                data_root,
                {
                    "action": "jobs_enqueue",
                    "job_type": "compile_node",
                    "dedupe_key": "compile:node_demo",
                    "payload": {"node_id": "node_demo"},
                },
            )
            _claim_status, reclaimed = service.handle_action(data_root, {"action": "jobs_claim", "job_types": ["compile_node"], "lease_seconds": 30})
            complete_status, completed = service.handle_action(
                data_root,
                {"action": "jobs_complete", "job_id": reclaimed["job"]["id"], "lease_token": reclaimed["job"]["lease_token"]},
            )
            list_status, listed = service.handle_action(data_root, {"action": "jobs_list", "status": "done"})

            self.assertEqual(complete_status, 200)
            self.assertEqual(completed["job"]["status"], "done")
            self.assertEqual(completed["job"]["lease_token"], "")
            self.assertEqual(list_status, 200)
            self.assertEqual(listed["jobs"][0]["id"], completed["job"]["id"])

    def test_ingest_jobs_run_next_executes_compile_job(self) -> None:
        service = self.import_backend_module("service")

        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            _node_status, node_payload = service.handle_action(
                data_root,
                {
                    "action": "remember",
                    "title": "Queued compile",
                    "body": "Queued compile claim.",
                    "type": "fact",
                },
            )
            node = node_payload["node"]
            service.handle_action(
                data_root,
                {
                    "action": "jobs_enqueue",
                    "job_type": "compile_node",
                    "dedupe_key": f"compile:{node['id']}",
                    "payload": {"node_id": node["id"]},
                },
            )

            run_status, run = service.handle_action(data_root, {"action": "jobs_list", "operation": "run_next", "job_types": ["compile_node"]})
            _inspect_status, inspected = service.handle_action(data_root, {"action": "inspect", "node_id": node["id"]})

            self.assertEqual(run_status, 200)
            self.assertTrue(run["ran"])
            self.assertTrue(run["ok"])
            self.assertEqual(run["job"]["status"], "done")
            self.assertEqual(inspected["node"]["compiled_page"]["freshness"], "fresh")

    def test_ingest_jobs_run_until_idle_drains_ready_jobs(self) -> None:
        service = self.import_backend_module("service")

        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            first = service.handle_action(
                data_root,
                {"action": "remember", "title": "First queued compile", "body": "First queued compile claim.", "type": "fact"},
            )[1]["node"]
            second = service.handle_action(
                data_root,
                {"action": "remember", "title": "Second queued compile", "body": "Second queued compile claim.", "type": "fact"},
            )[1]["node"]
            for node in (first, second):
                service.handle_action(
                    data_root,
                    {
                        "action": "jobs_enqueue",
                        "job_type": "compile_node",
                        "dedupe_key": f"compile:{node['id']}",
                        "payload": {"node_id": node["id"]},
                    },
                )

            run_status, run = service.handle_action(
                data_root,
                {
                    "action": "jobs_list",
                    "operation": "run_until_idle",
                    "job_types": ["compile_node"],
                    "max_jobs": 10,
                },
            )
            done_jobs = service.handle_action(data_root, {"action": "jobs_list", "status": "done"})[1]["jobs"]
            first_inspect = service.handle_action(data_root, {"action": "inspect", "node_id": first["id"]})[1]
            second_inspect = service.handle_action(data_root, {"action": "inspect", "node_id": second["id"]})[1]

            self.assertEqual(run_status, 200)
            self.assertTrue(run["ran"])
            self.assertTrue(run["ok"])
            self.assertTrue(run["idle"])
            self.assertEqual(run["jobs_run"], 2)
            self.assertEqual(len(done_jobs), 2)
            self.assertEqual(first_inspect["node"]["compiled_page"]["freshness"], "fresh")
            self.assertEqual(second_inspect["node"]["compiled_page"]["freshness"], "fresh")

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

    def test_search_and_context_share_memory_node_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            node = self.run_backend(
                data_root,
                {
                    "action": "remember",
                    "title": "Acme renewal owner",
                    "body": "Acme renewal owner is Dana.",
                    "type": "fact",
                },
            )["json"]["node"]

            search = self.run_backend(data_root, {"action": "search", "query": "renewal owner"})["json"]
            context = self.run_backend(data_root, {"action": "context", "query": "renewal owner"})["json"]

            for item in (search["results"][0], context["items"][0]):
                self.assertEqual(item["kind"], "memory_node")
                self.assertEqual(item["id"], node["id"])
                self.assertEqual(item["node_id"], node["id"])
                self.assertEqual(item["entity"], {"entity_type": "node", "entity_id": node["id"]})
                self.assertEqual(item["node"]["id"], node["id"])
                self.assertEqual(item["node"]["node_id"], node["id"])
                self.assertEqual(item["title"], "Acme renewal owner")
                self.assertEqual(item["type"], "fact")
                self.assertIn("match_sources", item)
                self.assertIn("source_chunk_matches", item)
                self.assertIn("storage_references", item)
                self.assertIn("compiled", item)
                self.assertIsInstance(item["relevance"], float)
                self.assertNotIn("score", item)

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

    def test_compile_input_hash_is_stable_for_unchanged_source_refs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace_root = Path(temp)
            data_root = workspace_root / "data" / "memory"
            source_path = workspace_root / "storage" / "generated" / "stable.md"
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_text("Stable source evidence.", encoding="utf-8")
            node = self.run_backend(
                data_root,
                {"action": "remember", "title": "Stable source", "body": "Stable source claim.", "type": "fact"},
            )["json"]["node"]
            self.run_backend(
                data_root,
                {
                    "action": "attach_file",
                    "node_id": node["id"],
                    "workspace_relative_path": "storage/generated/stable.md",
                    "title": "Stable source evidence",
                },
            )

            first = self.run_backend(data_root, {"action": "compile", "node_id": node["id"]})["json"]
            second = self.run_backend(data_root, {"action": "compile", "node_id": node["id"]})["json"]

            self.assertEqual(first["compile_run"]["input_hash"], second["compile_run"]["input_hash"])

    def test_ingest_source_inline_markdown_creates_verified_chunks_and_versions_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            service = self.import_backend_module("service")
            database = self.import_backend_module("database")

            status, first = service.handle_action(
                data_root,
                {
                    "action": "ingest_source",
                    "adapter_id": "inline_markdown",
                    "source_key": "notes:roadmap",
                    "title": "Roadmap note",
                    "body_markdown": "Roadmap says billing work is owned by Dana.",
                    "compile_after_ingest": True,
                },
            )
            second_status, second = service.handle_action(
                data_root,
                {
                    "action": "ingest_source",
                    "adapter_id": "inline_markdown",
                    "source_key": "notes:roadmap",
                    "title": "Roadmap note duplicate",
                    "body_markdown": "Roadmap says billing work is owned by Dana.",
                },
            )
            changed_status, changed = service.handle_action(
                data_root,
                {
                    "action": "ingest_source",
                    "adapter_id": "inline_markdown",
                    "source_key": "notes:roadmap",
                    "title": "Roadmap note changed",
                    "body_markdown": "Roadmap says billing work is owned by Lee.",
                },
            )
            source_query_status, source_query = service.handle_action(data_root, {"action": "source_query", "query": "Lee"})
            stale_source_query_status, stale_source_query = service.handle_action(data_root, {"action": "source_query", "query": "Dana"})

            with database.connect(data_root) as db:
                document_count = db.execute("SELECT COUNT(*) AS count FROM source_documents").fetchone()["count"]
                source_count = db.execute("SELECT COUNT(*) AS count FROM sources").fetchone()["count"]
                versions = [database.row_payload(row) or {} for row in db.execute("SELECT * FROM source_versions ORDER BY created_at")]
                chunks = [database.row_payload(row) or {} for row in db.execute("SELECT * FROM source_chunks ORDER BY created_at")]
                link_count = db.execute("SELECT COUNT(*) AS count FROM node_source_links").fetchone()["count"]

            fetch_status, fetched = service.handle_action(data_root, {"action": "fetch_chunks", "chunk_ids": [chunks[-1]["id"]]})

            self.assertEqual(status, 200)
            self.assertEqual(second_status, 200)
            self.assertEqual(changed_status, 200)
            self.assertTrue(first["document_created"])
            self.assertTrue(first["source_version_created"])
            self.assertFalse(second["document_created"])
            self.assertFalse(second["source_version_created"])
            self.assertFalse(changed["document_created"])
            self.assertTrue(changed["source_version_created"])
            self.assertEqual(second["node"]["id"], first["node"]["id"])
            self.assertEqual(changed["node"]["id"], first["node"]["id"])
            self.assertEqual(document_count, 1)
            self.assertEqual(source_count, 1)
            self.assertEqual(len(versions), 2)
            self.assertEqual(len(chunks), 2)
            self.assertEqual(link_count, 1)
            self.assertTrue(first["compiled"]["citations"])
            first_citation = first["compiled"]["citations"][0]
            first_compile_metadata = first["compiled"]["compile_run"]["metadata"]
            self.assertEqual(first_citation["source_version_id"], first["source_version"]["id"])
            self.assertEqual(first_citation["source_chunk_id"], chunks[0]["id"])
            self.assertIn(first["source_version"]["id"], first_compile_metadata["source_version_ids"])
            self.assertIn(chunks[0]["id"], first_compile_metadata["source_chunk_ids"])
            self.assertIn(chunks[0]["id"], first_compile_metadata["cited_source_chunk_ids"])
            self.assertEqual(versions[0]["hash_kind"], "canonical_body")
            self.assertEqual(versions[0]["extraction_status"], "available")
            self.assertTrue(versions[0]["body_path"].startswith("content/sources/"))
            self.assertTrue(chunks[-1]["body_path"].startswith("content/chunks/"))
            self.assertEqual(source_query_status, 200)
            self.assertEqual(source_query["results"][0]["chunk_id"], chunks[-1]["id"])
            self.assertEqual(source_query["results"][0]["freshness"], "fresh")
            self.assertEqual(stale_source_query_status, 200)
            self.assertEqual(stale_source_query["results"][0]["chunk_id"], chunks[0]["id"])
            self.assertEqual(stale_source_query["results"][0]["freshness"], "stale")
            self.assertEqual(fetch_status, 200)
            self.assertIn("owned by Lee", fetched["chunks"][0]["body"])

    def test_ingest_source_backend_events_include_graph_and_wiki(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"

            response = self.run_backend(
                data_root,
                {
                    "action": "ingest_source",
                    "adapter_id": "inline_markdown",
                    "source_key": "events:evidence",
                    "body_markdown": "Evidence note says the launch owner is Nia.",
                },
            )

            resources = {event["resource"] for event in response["app_events"]}
            self.assertEqual(response["status_code"], 200)
            self.assertIn("graph", resources)
            self.assertIn("wiki", resources)

    def test_ingest_source_chunks_long_body_and_cites_only_supporting_chunk(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            service = self.import_backend_module("service")
            database = self.import_backend_module("database")
            _node_status, node_payload = service.handle_action(
                data_root,
                {
                    "action": "remember",
                    "title": "Shipping owner",
                    "body": "The verified shipping owner is Priya.",
                    "type": "fact",
                },
            )
            filler = "Filler paragraph about unrelated planning and operational context.\n\n" * 70
            source_body = f"{filler}The verified shipping owner is Priya.\n"

            status, ingested = service.handle_action(
                data_root,
                {
                    "action": "ingest_source",
                    "adapter_id": "inline_markdown",
                    "node_id": node_payload["node"]["id"],
                    "source_key": "notes:shipping-owner",
                    "title": "Shipping source",
                    "body_markdown": source_body,
                    "compile_after_ingest": True,
                },
            )

            with database.connect(data_root) as db:
                chunks = [database.row_payload(row) or {} for row in db.execute("SELECT * FROM source_chunks ORDER BY chunk_index")]

            citation = ingested["compiled"]["citations"][0]
            cited_chunk = next(chunk for chunk in chunks if chunk["id"] == citation["source_chunk_id"])
            source_query_status, source_query = service.handle_action(data_root, {"action": "source_query", "query": "Priya owner"})
            search_status, search = service.handle_action(data_root, {"action": "search", "query": "Priya owner"})
            context_status, context = service.handle_action(data_root, {"action": "context", "query": "Priya owner"})
            self.assertEqual(status, 200)
            self.assertGreater(len(chunks), 1)
            self.assertGreater(cited_chunk["chunk_index"], 0)
            self.assertIn("verified shipping owner is Priya", citation["quote"])
            self.assertEqual(source_query_status, 200)
            self.assertEqual(source_query["results"][0]["chunk_id"], cited_chunk["id"])
            self.assertIn("verified shipping owner is Priya", source_query["results"][0]["summary"])
            self.assertEqual(search_status, 200)
            self.assertEqual(search["results"][0]["source_chunk_matches"][0]["chunk_id"], cited_chunk["id"])
            self.assertEqual(search["results"][0]["source_chunk_matches"][0]["citations"][0]["source_chunk_id"], cited_chunk["id"])
            self.assertEqual(context_status, 200)
            self.assertEqual(context["items"][0]["source_chunk_matches"][0]["chunk_id"], cited_chunk["id"])
            self.assertEqual(context["items"][0]["source_chunk_matches"][0]["citations"][0]["source_chunk_id"], cited_chunk["id"])

    def test_compile_does_not_cite_unrelated_source_chunk(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            service = self.import_backend_module("service")
            _node_status, node_payload = service.handle_action(
                data_root,
                {
                    "action": "remember",
                    "title": "Shipping owner",
                    "body": "The verified shipping owner is Priya.",
                    "type": "fact",
                },
            )

            _status, ingested = service.handle_action(
                data_root,
                {
                    "action": "ingest_source",
                    "adapter_id": "inline_markdown",
                    "node_id": node_payload["node"]["id"],
                    "source_key": "notes:unrelated",
                    "title": "Unrelated source",
                    "body_markdown": "The renewal checklist is owned by Dana.",
                    "compile_after_ingest": True,
                },
            )

            finding_types = {finding["finding_type"] for finding in ingested["compiled"]["lint_findings"]}
            self.assertEqual(ingested["compiled"]["citations"], [])
            self.assertIn("missing_citation", finding_types)

    def test_compile_cites_paraphrased_source_chunk(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            service = self.import_backend_module("service")
            _node_status, node_payload = service.handle_action(
                data_root,
                {
                    "action": "remember",
                    "title": "Renewal evidence",
                    "body": "Dana owns the renewal evidence.",
                    "type": "fact",
                },
            )

            _status, ingested = service.handle_action(
                data_root,
                {
                    "action": "ingest_source",
                    "adapter_id": "inline_markdown",
                    "node_id": node_payload["node"]["id"],
                    "source_key": "notes:renewal-evidence",
                    "title": "Renewal evidence source",
                    "body_markdown": "The renewal evidence is owned by Dana.",
                    "compile_after_ingest": True,
                },
            )

            citation = ingested["compiled"]["citations"][0]
            self.assertIn("renewal evidence is owned by Dana", citation["quote"])
            self.assertTrue(citation["source_chunk_id"])
            self.assertTrue(citation["quote_sha256"])

    def test_compile_cites_multi_sentence_source_window(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            service = self.import_backend_module("service")
            _node_status, node_payload = service.handle_action(
                data_root,
                {
                    "action": "remember",
                    "title": "Renewal launch",
                    "body": "Dana owns the renewal evidence and the launch date is July 15.",
                    "type": "fact",
                },
            )

            _status, ingested = service.handle_action(
                data_root,
                {
                    "action": "ingest_source",
                    "adapter_id": "inline_markdown",
                    "node_id": node_payload["node"]["id"],
                    "source_key": "notes:renewal-launch",
                    "title": "Renewal launch source",
                    "body_markdown": "The renewal evidence is owned by Dana. The launch date is July 15.",
                    "compile_after_ingest": True,
                },
            )

            citation = ingested["compiled"]["citations"][0]
            self.assertIn("renewal evidence is owned by Dana", citation["quote"])
            self.assertIn("launch date is July 15", citation["quote"])
            self.assertTrue(citation["source_chunk_id"])
            self.assertTrue(citation["quote_sha256"])

    def test_ingest_source_storage_file_creates_new_versions_for_local_text_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace_root = Path(temp)
            data_root = workspace_root / "data" / "memory"
            source_path = workspace_root / "storage" / "generated" / "notes" / "handoff.md"
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_text("Handoff says renewal evidence is owned by Dana.", encoding="utf-8")
            service = self.import_backend_module("service")
            storage_file_sources = sys.modules["storage_file_sources"]
            database = self.import_backend_module("database")
            calls: list[tuple[str, dict]] = []

            def file_payload() -> dict:
                stat = source_path.stat()
                return {
                    "file_id": "generated:notes/handoff.md",
                    "id": "generated:notes/handoff.md",
                    "name": "handoff.md",
                    "role": "generated",
                    "relative_path": "notes/handoff.md",
                    "workspace_relative_path": "storage/generated/notes/handoff.md",
                    "extension": ".md",
                    "size_bytes": stat.st_size,
                    "sha256": sha256(source_path.read_bytes()).hexdigest(),
                    "modified_at": str(stat.st_mtime_ns),
                    "content_type": "text/markdown",
                    "preview_kind": "markdown",
                }

            def fake_storage_surface(_data_root: Path, tool_name: str, arguments: dict) -> dict:
                calls.append((tool_name, dict(arguments)))
                if tool_name == "storage_reference_resolve":
                    self.assertEqual(arguments["entity_id"], "file_handoff")
                    return {"status_code": 200, "file": file_payload()}
                if tool_name == "storage_file_info":
                    return {"status_code": 200, "file": file_payload()}
                if tool_name == "storage_preview_text":
                    return {"status_code": 200, "file": file_payload(), "preview_text": source_path.read_text(encoding="utf-8")}
                if tool_name == "storage_read_file":
                    return {
                        "status_code": 200,
                        "file": file_payload(),
                        "content_base64": b64encode(source_path.read_bytes()).decode("ascii"),
                    }
                raise AssertionError(f"unexpected Storage tool {tool_name}")

            original_surface = storage_file_sources._storage_file_surface

            try:
                storage_file_sources._storage_file_surface = fake_storage_surface
                first_status, first = service.handle_action(
                    data_root,
                    {
                        "action": "ingest_source",
                        "adapter_id": "storage_file",
                        "file_id": "file_handoff",
                        "title": "Handoff note",
                        "compile_after_ingest": True,
                    },
                )
                second_status, second = service.handle_action(
                    data_root,
                    {
                        "action": "ingest_source",
                        "adapter_id": "storage_file",
                        "file_id": "file_handoff",
                        "workspace_relative_path": "storage/generated/notes/handoff.md",
                        "title": "Handoff note duplicate",
                    },
                )
                source_path.write_text("Handoff says renewal evidence is owned by Dana.\n", encoding="utf-8")
                byte_changed_status, byte_changed = service.handle_action(
                    data_root,
                    {
                        "action": "ingest_source",
                        "adapter_id": "storage_file",
                        "file_id": "file_handoff",
                        "workspace_relative_path": "storage/generated/notes/handoff.md",
                        "title": "Handoff note byte changed",
                    },
                )
                source_path.write_text("Handoff says renewal evidence is owned by Marta.", encoding="utf-8")
                changed_status, changed = service.handle_action(
                    data_root,
                    {
                        "action": "ingest_source",
                        "adapter_id": "storage_file",
                        "file_id": "file_handoff",
                        "workspace_relative_path": "storage/generated/notes/handoff.md",
                        "title": "Handoff note changed",
                    },
                )
                rejected = self.run_backend(
                    data_root,
                    {
                        "action": "ingest_source",
                        "adapter_id": "storage_file",
                        "workspace_relative_path": "../outside.md",
                    },
                )
                fresh_status, fresh_query = service.handle_action(data_root, {"action": "source_query", "query": "Marta"})
                stale_status, stale_query = service.handle_action(data_root, {"action": "source_query", "query": "Dana"})
            finally:
                storage_file_sources._storage_file_surface = original_surface

            with database.connect(data_root) as db:
                source_document = database.row_payload(db.execute("SELECT * FROM source_documents").fetchone()) or {}
                source = database.row_payload(db.execute("SELECT * FROM sources").fetchone()) or {}
                versions = [database.row_payload(row) or {} for row in db.execute("SELECT * FROM source_versions ORDER BY created_at")]
                chunks = [database.row_payload(row) or {} for row in db.execute("SELECT * FROM source_chunks ORDER BY created_at")]

            fetch_status, fetched = service.handle_action(data_root, {"action": "fetch_chunks", "chunk_ids": [chunks[-1]["id"]]})

            self.assertEqual(first_status, 200)
            self.assertEqual(second_status, 200)
            self.assertEqual(byte_changed_status, 200)
            self.assertEqual(changed_status, 200)
            self.assertEqual(
                [tool_name for tool_name, _arguments in calls[:4]],
                ["storage_reference_resolve", "storage_file_info", "storage_preview_text", "storage_read_file"],
            )
            self.assertEqual(calls[0][1]["entity_id"], "file_handoff")
            self.assertTrue(
                all(
                    arguments["workspace_relative_path"] == "storage/generated/notes/handoff.md"
                    for tool_name, arguments in calls
                    if tool_name in {"storage_file_info", "storage_preview_text", "storage_read_file"}
                )
            )
            self.assertTrue(first["source_version_created"])
            self.assertFalse(second["source_version_created"])
            self.assertTrue(byte_changed["source_version_created"])
            self.assertTrue(changed["source_version_created"])
            self.assertEqual(first["node"]["id"], changed["node"]["id"])
            self.assertEqual(rejected["status_code"], 400)
            self.assertIn("workspace_relative_path", rejected["json"]["detail"])
            self.assertEqual(source_document["source_key"], "storage_file:file_handoff")
            self.assertEqual(source_document["owning_app_id"], "storage")
            self.assertEqual(source_document["workspace_relative_path"], "storage/generated/notes/handoff.md")
            self.assertEqual(source["file_id"], "file_handoff")
            self.assertEqual(len(versions), 3)
            self.assertEqual(len(chunks), 3)
            self.assertEqual({version["hash_kind"] for version in versions}, {"file_bytes"})
            self.assertNotEqual(versions[0]["version_hash"], versions[1]["version_hash"])
            self.assertEqual(versions[0]["body_sha256"], versions[1]["body_sha256"])
            self.assertTrue(all(version["body_path"].startswith("content/sources/") for version in versions))
            self.assertTrue(all(chunk["body_path"].startswith("content/chunks/") for chunk in chunks))
            self.assertEqual(chunks[-1]["locator"], "storage/generated/notes/handoff.md")
            self.assertEqual(chunks[-1]["locator_kind"], "workspace_relative_path")
            self.assertEqual(fresh_status, 200)
            self.assertEqual(fresh_query["results"][0]["chunk_id"], chunks[-1]["id"])
            self.assertEqual(fresh_query["results"][0]["freshness"], "fresh")
            self.assertEqual(stale_status, 200)
            self.assertIn(stale_query["results"][0]["chunk_id"], {chunks[0]["id"], chunks[1]["id"]})
            self.assertEqual(stale_query["results"][0]["freshness"], "stale")
            self.assertEqual(fetch_status, 200)
            self.assertIn("owned by Marta", fetched["chunks"][0]["body"])

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

    def test_ingest_app_entity_snapshots_reference_surface_and_compiles_chunks(self) -> None:
        source_ingestion = self.import_backend_module("source_ingestion")
        service = self.import_backend_module("service")
        database = self.import_backend_module("database")
        original_fetch = source_ingestion.fetch_app_entity_source
        try:
            source_ingestion.fetch_app_entity_source = lambda _data_root, request: {
                "exists": True,
                "app_id": request["owning_app_id"],
                "entity_type": request["entity_type"],
                "entity_id": request["entity_id"],
                "title": "Acme CRM account",
                "summary": "Acme CRM account says the renewal owner is Dana.",
                "deep_link": "/app/crm/accounts/acct_acme",
            }
            with tempfile.TemporaryDirectory() as temp:
                data_root = Path(temp) / "data" / "memory"
                status, result = service.handle_action(
                    data_root,
                    {
                        "action": "ingest_source",
                        "adapter_id": "app_entity",
                        "owning_app_id": "crm",
                        "entity_type": "account",
                        "entity_id": "acct_acme",
                        "compile_after_ingest": True,
                    },
                )
                with database.connect(data_root) as db:
                    document = database.row_payload(db.execute("SELECT * FROM source_documents").fetchone()) or {}
                    version = database.row_payload(db.execute("SELECT * FROM source_versions").fetchone()) or {}
                    chunk = database.row_payload(db.execute("SELECT * FROM source_chunks").fetchone()) or {}

                self.assertEqual(status, 200)
                self.assertEqual(result["adapter_id"], "app_entity")
                self.assertEqual(document["source_key"], "app_entity:crm:account:acct_acme")
                self.assertEqual(version["hash_kind"], "reference_snapshot")
                self.assertEqual(version["extraction_status"], "available")
                self.assertEqual(version["source_document_id"], document["id"])
                self.assertEqual(chunk["source_version_id"], version["id"])
                self.assertEqual(chunk["locator"], "/app/crm/accounts/acct_acme")
                self.assertTrue(result["compiled"]["citations"])
                self.assertEqual(result["compiled"]["citations"][0]["source_chunk_id"], chunk["id"])
        finally:
            source_ingestion.fetch_app_entity_source = original_fetch

    def test_inspect_source_reports_freshness_and_column_backed_job_provenance(self) -> None:
        service = self.import_backend_module("service")
        database = self.import_backend_module("database")

        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            status, ingested = service.handle_action(
                data_root,
                {
                    "action": "ingest_source",
                    "adapter_id": "inline_markdown",
                    "source_key": "unit-source",
                    "title": "Unit source",
                    "body_markdown": "Unit source says the owner is Dana.",
                    "compile_after_ingest": False,
                },
            )
            source_document = ingested["source_document"]
            source_version = ingested["source_version"]
            inspect_status, inspected = service.handle_action(
                data_root,
                {"action": "inspect_source", "source_document_id": source_document["id"]},
            )

            with database.connect(data_root) as db:
                job = database.row_payload(db.execute("SELECT * FROM ingest_jobs").fetchone()) or {}

            self.assertEqual(status, 200)
            self.assertEqual(inspect_status, 200)
            self.assertEqual(inspected["source_document"]["kind"], "source_document")
            self.assertEqual(inspected["freshness"]["state"], "fresh")
            self.assertEqual(inspected["freshness"]["latest_source_version_id"], source_version["id"])
            self.assertEqual(inspected["versions"][0]["kind"], "source_version")
            self.assertEqual(inspected["versions"][0]["freshness"], "fresh")
            self.assertEqual(inspected["chunks"][0]["kind"], "source_chunk")
            self.assertEqual(inspected["chunks"][0]["freshness"], "fresh")
            self.assertEqual(inspected["chunks"][0]["citations"], [])
            self.assertEqual(job["source_document_id"], source_document["id"])
            self.assertEqual(job["source_version_id"], source_version["id"])
            self.assertEqual(inspected["ingest_jobs"][0]["source_document_id"], source_document["id"])
            self.assertEqual(inspected["ingest_jobs"][0]["source_version_id"], source_version["id"])

    def test_fetch_app_entity_source_discovers_reference_tools_and_passes_entity_type(self) -> None:
        app_entity_sources = self.import_backend_module("app_entity_sources")
        original_run = app_entity_sources.subprocess.run
        original_which = app_entity_sources.shutil.which
        calls: list[list[str]] = []

        def fake_run(args, **_kwargs):
            calls.append(list(args))
            if args[:5] == ["maverick", "app", "crm", "mcp", "list"]:
                return subprocess.CompletedProcess(
                    args,
                    0,
                    stdout=json.dumps(
                        {
                            "tools": [
                                {"name": "crm_reference_manifest"},
                                {"name": "crm_reference_resolve"},
                                {"name": "crm_reference_summarize"},
                            ]
                        }
                    ),
                    stderr="",
                )
            if "crm_reference_manifest" in args:
                return subprocess.CompletedProcess(
                    args,
                    0,
                    stdout=json.dumps({"status_code": 200, "entity_types": [{"entity_type": "account"}]}),
                    stderr="",
                )
            if "crm_reference_summarize" in args:
                return subprocess.CompletedProcess(
                    args,
                    0,
                    stdout=json.dumps(
                        {
                            "status_code": 200,
                            "exists": True,
                            "title": "Acme account",
                            "summary": "Acme account summary.",
                        }
                    ),
                    stderr="",
                )
            if "crm_reference_resolve" in args:
                return subprocess.CompletedProcess(
                    args,
                    0,
                    stdout=json.dumps(
                        {
                            "status_code": 200,
                            "exists": True,
                            "app_id": "crm",
                            "entity_type": "account",
                            "entity_id": "account:acct_acme",
                            "title": "Acme account",
                            "deep_link": "/app/crm/accounts/acct_acme",
                        }
                    ),
                    stderr="",
                )
            return subprocess.CompletedProcess(args, 1, stdout=json.dumps({"status_code": 404}), stderr="")

        try:
            app_entity_sources.shutil.which = lambda _name: "/usr/bin/maverick"
            app_entity_sources.subprocess.run = fake_run
            with tempfile.TemporaryDirectory() as temp:
                data_root = Path(temp) / "data" / "memory"
                snapshot = app_entity_sources.fetch_app_entity_source(
                    data_root,
                    {"owning_app_id": "crm", "entity_type": "account", "entity_id": "acct_acme"},
                )
        finally:
            app_entity_sources.subprocess.run = original_run
            app_entity_sources.shutil.which = original_which

        summarize_call = next(call for call in calls if "crm_reference_summarize" in call)
        resolve_call = next(call for call in calls if "crm_reference_resolve" in call)
        self.assertEqual(snapshot["summary"], "Acme account summary.")
        self.assertEqual(snapshot["deep_link"], "/app/crm/accounts/acct_acme")
        self.assertIn("--entity-type", summarize_call)
        self.assertIn("--entity-id", summarize_call)
        self.assertEqual(summarize_call[summarize_call.index("--entity-type") + 1], "account")
        self.assertEqual(summarize_call[summarize_call.index("--entity-id") + 1], "acct_acme")
        self.assertEqual(resolve_call[resolve_call.index("--entity-type") + 1], "account")
        self.assertEqual(resolve_call[resolve_call.index("--entity-id") + 1], "acct_acme")

    def test_remote_storage_ingest_prepares_preview_before_source_sync(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            storage_sources = self.import_backend_module("storage_sources")
            storage_ingestion = self.import_backend_module("storage_ingestion")
            service = self.import_backend_module("service")
            original_preview = storage_sources._storage_preview_surface
            original_sync = storage_ingestion.sync_sources
            try:
                storage_sources._storage_preview_surface = lambda _data_root, _request: {
                    "status_code": 200,
                    "preview_text": "Prepared Drive preview says the owner is Dana.",
                    "source_version": "rev-prepared",
                    "file": {"display_path": "/Drive/Prepared.md"},
                }

                def guarded_sync(db, *, data_root, node_id, refs, timestamp, prepared_snapshots=None):
                    ref_payload = database.row_payload(refs[0]) if refs else {}
                    metadata = ref_payload.get("metadata") if isinstance(ref_payload.get("metadata"), dict) else {}
                    self.assertIn("ingest_preview_text", metadata)
                    return original_sync(db, data_root=data_root, node_id=node_id, refs=refs, timestamp=timestamp, prepared_snapshots=prepared_snapshots)

                database = self.import_backend_module("database")
                storage_ingestion.sync_sources = guarded_sync
                status, result = service.handle_action(
                    data_root,
                    {
                        "action": "ingest_storage_source",
                        "memory_source": self.drive_memory_source(source_version="rev-prepared"),
                    },
                )
            finally:
                storage_sources._storage_preview_surface = original_preview
                storage_ingestion.sync_sources = original_sync

            self.assertEqual(status, 200)
            self.assertEqual(result["sources"][0]["metadata"]["source_version"], "rev-prepared")

    def test_compile_uses_prepared_source_snapshots_for_remote_refs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            storage_sources = self.import_backend_module("storage_sources")
            wiki = self.import_backend_module("wiki")
            service = self.import_backend_module("service")
            original_preview = storage_sources._storage_preview_surface
            original_sync = wiki.sync_sources
            try:
                storage_sources._storage_preview_surface = lambda _data_root, _request: {
                    "status_code": 200,
                    "preview_text": "Prepared compile preview says the owner is Dana.",
                    "source_version": "rev-compile",
                    "file": {"display_path": "/Drive/Compile.md"},
                }

                def guarded_sync(db, *, data_root, node_id, refs, timestamp, prepared_snapshots=None):
                    self.assertIsInstance(prepared_snapshots, dict)
                    self.assertTrue(refs)
                    self.assertIn(refs[0]["id"], prepared_snapshots)
                    return original_sync(db, data_root=data_root, node_id=node_id, refs=refs, timestamp=timestamp, prepared_snapshots=prepared_snapshots)

                wiki.sync_sources = guarded_sync
                _node_status, node_payload = service.handle_action(
                    data_root,
                    {
                        "action": "remember",
                        "title": "Remote ref compile",
                        "body": "Remote ref compile says the owner is Dana.",
                    },
                )
                node_id = node_payload["node"]["id"]
                service.handle_action(
                    data_root,
                    {
                        "action": "attach_file",
                        "node_id": node_id,
                        "owning_app_id": "storage",
                        "entity_type": "file",
                        "entity_id": "file_drive_compile",
                        "provider": "google_drive",
                        "metadata": {
                            "provider": "google_drive",
                            "connection_id": "drive_conn_acme",
                            "drive_file_id": "drive_compile",
                            "source_version": "rev-compile",
                        },
                    },
                )
                status, compiled = service.handle_action(data_root, {"action": "compile", "node_id": node_id})
            finally:
                storage_sources._storage_preview_surface = original_preview
                wiki.sync_sources = original_sync

            self.assertEqual(status, 200)
            self.assertEqual(compiled["compiled_page"]["freshness"], "fresh")

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
                source_query_status, source_query = service.handle_action(data_root, {"action": "source_query", "query": "Dana owner"})
            finally:
                storage_sources._storage_preview_surface = original_surface

            with database.connect(data_root) as db:
                ref_count = db.execute("SELECT COUNT(*) AS count FROM external_refs").fetchone()["count"]
                version = database.row_payload(db.execute("SELECT * FROM source_versions").fetchone()) or {}
                source = database.row_payload(db.execute("SELECT * FROM sources").fetchone()) or {}
                source_document = database.row_payload(db.execute("SELECT * FROM source_documents").fetchone()) or {}
                source_chunk = database.row_payload(db.execute("SELECT * FROM source_chunks").fetchone()) or {}
                job_count = db.execute("SELECT COUNT(*) AS count FROM ingest_jobs").fetchone()["count"]
            fetch_status, fetched = service.handle_action(data_root, {"action": "fetch_chunks", "chunk_ids": [source_chunk["id"]]})
            inspect_source_status, inspected_source = service.handle_action(
                data_root,
                {"action": "inspect_source", "source_document_id": source_document["id"]},
            )

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
            self.assertEqual(first["compiled"]["citations"][0]["source_chunk_id"], source_chunk["id"])
            self.assertEqual(first["compiled"]["citations"][0]["locator_kind"], "preview_text")
            self.assertIsInstance(first["compiled"]["citations"][0]["char_start"], int)
            self.assertIsInstance(first["compiled"]["citations"][0]["char_end"], int)
            self.assertTrue(first["compiled"]["citations"][0]["quote_sha256"])
            self.assertIn(version["id"], first["compiled"]["compile_run"]["metadata"]["source_version_ids"])
            self.assertIn(source_chunk["id"], first["compiled"]["compile_run"]["metadata"]["source_chunk_ids"])
            self.assertIn(source_chunk["id"], first["compiled"]["compile_run"]["metadata"]["cited_source_chunk_ids"])
            self.assertEqual(
                first["compiled"]["citations"][0]["storage_reference"]["preview_request"]["tool"],
                "storage_drive_preview",
            )
            self.assertIn("renewal owner is Dana", version["extracted_text"])
            self.assertEqual(version["source_document_id"], source_document["id"])
            self.assertTrue(version["body_path"].startswith("content/sources/"))
            self.assertTrue(version["body_sha256"])
            self.assertGreater(version["body_bytes"], 0)
            self.assertEqual(source_document["source_key"], "remote_storage_file:file_drive_plan")
            self.assertEqual(source_chunk["source_version_id"], version["id"])
            self.assertTrue(source_chunk["body_path"].startswith("content/chunks/"))
            self.assertEqual(source_chunk["char_start"], 0)
            self.assertGreater(source_chunk["char_end"], 0)
            self.assertNotIn("ingest_preview_text", source["metadata"])
            self.assertNotIn("ingest_preview_truncated", source["metadata"])
            self.assertEqual(context_status, 200)
            self.assertEqual(search_status, 200)
            self.assertEqual(wiki_status, 200)
            self.assertEqual(source_query_status, 200)
            self.assertEqual(source_query["results"][0]["kind"], "source_chunk")
            self.assertEqual(source_query["results"][0]["chunk_id"], source_chunk["id"])
            self.assertEqual(source_query["results"][0]["citations"][0]["source_chunk_id"], source_chunk["id"])
            self.assertEqual(job_count, 0)
            self.assertIn("source_chunk", search["results"][0]["match_sources"])
            self.assertEqual(search["results"][0]["source_chunk_matches"][0]["chunk_id"], source_chunk["id"])
            self.assertEqual(search["results"][0]["source_chunk_matches"][0]["citations"][0]["source_chunk_id"], source_chunk["id"])
            self.assertIn("source_chunk", context["items"][0]["match_sources"])
            self.assertEqual(context["items"][0]["source_chunk_matches"][0]["source_version_id"], version["id"])
            self.assertEqual(context["items"][0]["source_chunk_matches"][0]["citations"][0]["source_chunk_id"], source_chunk["id"])
            self.assertEqual(fetch_status, 200)
            self.assertEqual(fetched["chunks"][0]["id"], source_chunk["id"])
            self.assertEqual(fetched["chunks"][0]["kind"], "source_chunk")
            self.assertEqual(fetched["chunks"][0]["chunk_id"], source_chunk["id"])
            self.assertEqual(fetched["chunks"][0]["freshness"], "fresh")
            self.assertEqual(fetched["chunks"][0]["citations"][0]["source_chunk_id"], source_chunk["id"])
            self.assertIn("renewal owner is Dana", fetched["chunks"][0]["body"])
            self.assertEqual(inspect_source_status, 200)
            self.assertEqual(inspected_source["source_document"]["id"], source_document["id"])
            self.assertEqual(inspected_source["versions"][0]["id"], version["id"])
            self.assertEqual(inspected_source["chunks"][0]["id"], source_chunk["id"])
            self.assertEqual(inspected_source["linked_nodes"][0]["id"], first["node"]["id"])
            context_ref = context["items"][0]["storage_references"][0]
            search_ref = search["results"][0]["storage_references"][0]
            wiki_ref = wiki_result["results"][0]["storage_references"][0]
            self.assertEqual(context_ref["stable_storage_file_id"], "file_drive_plan")
            self.assertEqual(search_ref["preview_request"]["arguments"]["stable_storage_file_id"], "file_drive_plan")
            self.assertEqual(wiki_ref["deep_link"], "/app/storage/files/file_drive_plan")
            self.assertEqual(context["items"][0]["compiled"]["storage_references"][0]["drive_file_id"], "drive_plan")

    def test_ingest_source_accepts_remote_storage_file_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            service = self.import_backend_module("service")
            database = self.import_backend_module("database")

            status, ingested = service.handle_action(
                data_root,
                {
                    "action": "ingest_source",
                    "adapter_id": "remote_storage_file",
                    "title": "Drive board plan",
                    "memory_source": self.drive_memory_source(
                        storage_file_id="file_drive_generic_ingest",
                        drive_file_id="drive_generic_ingest",
                    ),
                    "preview_text": "Drive board plan says the accountable owner is Lee.",
                    "compile_after_ingest": True,
                },
            )
            source_query_status, source_query = service.handle_action(data_root, {"action": "source_query", "query": "Lee"})

            with database.connect(data_root) as db:
                source_document = database.row_payload(db.execute("SELECT * FROM source_documents").fetchone()) or {}
                job_count = db.execute("SELECT COUNT(*) AS count FROM ingest_jobs").fetchone()["count"]
                db.execute("UPDATE source_versions SET extracted_text = ''")
                db.commit()
            fts_only_status, fts_only_query = service.handle_action(data_root, {"action": "source_query", "query": "Lee"})

            self.assertEqual(status, 200)
            self.assertEqual(ingested["storage_identity"]["entity_id"], "file_drive_generic_ingest")
            self.assertEqual(source_document["adapter_id"], "remote_storage_file")
            self.assertEqual(source_document["source_key"], "remote_storage_file:file_drive_generic_ingest")
            self.assertEqual(ingested["compiled"]["citations"][0]["source_version"], "rev-1")
            self.assertEqual(source_query_status, 200)
            self.assertEqual(source_query["results"][0]["kind"], "source_chunk")
            self.assertEqual(source_query["results"][0]["freshness"], "fresh")
            self.assertEqual(fts_only_status, 200)
            self.assertEqual(fts_only_query["results"][0]["kind"], "source_chunk")
            self.assertEqual(fts_only_query["results"][0]["chunk_id"], source_query["results"][0]["chunk_id"])
            self.assertEqual(job_count, 0)

    def test_ingest_storage_source_without_compile_materializes_source_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            service = self.import_backend_module("service")
            database = self.import_backend_module("database")

            status, ingested = service.handle_action(
                data_root,
                {
                    "action": "ingest_storage_source",
                    "title": "Drive source only",
                    "memory_source": self.drive_memory_source(
                        storage_file_id="file_drive_source_only",
                        drive_file_id="drive_source_only",
                    ),
                    "preview_text": "Drive source only says the accountable owner is Riley.",
                },
            )
            source_query_status, source_query = service.handle_action(data_root, {"action": "source_query", "query": "Riley"})

            with database.connect(data_root) as db:
                source_document_count = db.execute("SELECT COUNT(*) AS count FROM source_documents").fetchone()["count"]
                source_version_count = db.execute("SELECT COUNT(*) AS count FROM source_versions").fetchone()["count"]
                source_chunk_count = db.execute("SELECT COUNT(*) AS count FROM source_chunks").fetchone()["count"]
                fresh_wiki_count = db.execute("SELECT COUNT(*) AS count FROM wiki_pages WHERE freshness = 'fresh'").fetchone()["count"]

            self.assertEqual(status, 200)
            self.assertTrue(ingested["sources"])
            self.assertIsNone(ingested["compiled"])
            self.assertEqual(source_document_count, 1)
            self.assertEqual(source_version_count, 1)
            self.assertEqual(source_chunk_count, 1)
            self.assertEqual(fresh_wiki_count, 0)
            self.assertEqual(source_query_status, 200)
            self.assertEqual(source_query["results"][0]["kind"], "source_chunk")
            self.assertEqual(source_query["results"][0]["freshness"], "fresh")

    def test_remote_storage_preview_body_changes_create_new_source_version_even_with_same_storage_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            service = self.import_backend_module("service")
            database = self.import_backend_module("database")
            source = self.drive_memory_source(source_version="rev-same")

            first_status, first = service.handle_action(
                data_root,
                {
                    "action": "ingest_storage_source",
                    "title": "Drive preview body",
                    "memory_source": source,
                    "preview_text": "Drive preview says renewal owner is Dana.",
                    "compile_after_ingest": True,
                },
            )
            second_status, second = service.handle_action(
                data_root,
                {
                    "action": "ingest_storage_source",
                    "title": "Drive preview body",
                    "memory_source": source,
                    "preview_text": "Drive preview says renewal owner is Dana. Added verified appendix.",
                    "compile_after_ingest": True,
                },
            )

            with database.connect(data_root) as db:
                versions = [
                    database.row_payload(row) or {}
                    for row in db.execute("SELECT * FROM source_versions ORDER BY created_at")
                ]
                chunks = [
                    database.row_payload(row) or {}
                    for row in db.execute("SELECT * FROM source_chunks ORDER BY created_at")
                ]

            self.assertEqual(first_status, 200)
            self.assertEqual(second_status, 200)
            self.assertEqual(second["node"]["id"], first["node"]["id"])
            self.assertEqual(len(versions), 2)
            self.assertEqual({version["metadata"]["source_version"] for version in versions}, {"rev-same"})
            self.assertNotEqual(versions[0]["version_hash"], versions[1]["version_hash"])
            self.assertNotEqual(versions[0]["body_sha256"], versions[1]["body_sha256"])
            self.assertEqual({chunk["source_version_id"] for chunk in chunks}, {version["id"] for version in versions})

    def test_ingest_storage_source_accepts_empty_preview_text_without_second_storage_preview(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            storage_sources = self.import_backend_module("storage_sources")
            service = self.import_backend_module("service")
            database = self.import_backend_module("database")
            sources = self.import_backend_module("sources")
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
                remote_ref = db.execute("SELECT * FROM external_refs").fetchone()
                snapshot_without_preview = sources.source_snapshot(remote_ref, data_root, include_remote_preview=False)
                chunk_count = db.execute("SELECT COUNT(*) AS count FROM source_chunks").fetchone()["count"]

            self.assertEqual(status, 200)
            self.assertEqual(result["compiled"]["compiled_page"]["freshness"], "fresh")
            self.assertEqual(version["extracted_text"], "")
            self.assertEqual(version["hash_kind"], "reference_snapshot")
            self.assertEqual(version["metadata"]["hash_kind"], "reference_snapshot")
            self.assertEqual(snapshot_without_preview["hash_kind"], "reference_snapshot")
            self.assertEqual(version["extraction_status"], "unavailable")
            self.assertEqual(version["body_path"], "")
            self.assertEqual(chunk_count, 0)
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

    def test_platform_storage_file_source_uses_storage_mcp_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            storage_file_sources = self.import_backend_module("storage_file_sources")
            calls: list[list[str]] = []
            original_run = storage_file_sources.subprocess.run
            original_which = storage_file_sources.shutil.which

            class Completed:
                returncode = 0
                stdout = json.dumps({"status_code": 200, "file": {"workspace_relative_path": "storage/generated/notes/handoff.md"}})

            def fake_run(args: list[str], **_kwargs: object) -> Completed:
                calls.append(args)
                return Completed()

            try:
                storage_file_sources.shutil.which = lambda _name: "/usr/bin/maverick"
                storage_file_sources.subprocess.run = fake_run
                result = storage_file_sources.default_storage_file_surface(
                    data_root,
                    "storage_file_info",
                    {"workspace_relative_path": "storage/generated/notes/handoff.md"},
                )
            finally:
                storage_file_sources.subprocess.run = original_run
                storage_file_sources.shutil.which = original_which

            self.assertEqual(result["file"]["workspace_relative_path"], "storage/generated/notes/handoff.md")
            self.assertEqual(calls[0][:7], ["maverick", "app", "storage", "mcp", "call", "storage_file_info", "--json"])
            self.assertIn("--workspace-relative-path", calls[0])
            self.assertIn("storage/generated/notes/handoff.md", calls[0])

    def test_storage_file_source_local_fallback_requires_explicit_dev_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "memory"
            storage_file_sources = self.import_backend_module("storage_file_sources")
            original_which = storage_file_sources.shutil.which
            original_flag = os.environ.pop("MAVERICK_MEMORY_ALLOW_LOCAL_STORAGE_FALLBACK", None)
            try:
                storage_file_sources.shutil.which = lambda _name: None
                with self.assertRaises(storage_file_sources.MemoryValidationError):
                    storage_file_sources.default_storage_file_surface(
                        data_root,
                        "storage_file_info",
                        {"workspace_relative_path": "storage/generated/notes/handoff.md"},
                    )
            finally:
                storage_file_sources.shutil.which = original_which
                if original_flag is not None:
                    os.environ["MAVERICK_MEMORY_ALLOW_LOCAL_STORAGE_FALLBACK"] = original_flag

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
            self.assertTrue(citation["source_chunk_id"].startswith("sch_"))
            self.assertEqual(citation["locator_kind"], "preview_text")
            self.assertTrue(citation["quote_sha256"])
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
            source_query = service.handle_action(data_root, {"action": "source_query", "query": "changed file"})[1]
            ready_jobs = service.handle_action(
                data_root,
                {"action": "jobs_list", "status": "ready", "job_type": "requires_storage_reindex"},
            )[1]
            old_ingest_jobs = service.handle_action(data_root, {"action": "jobs_list", "job_type": "ingest_source"})[1]
            reindex_run = service.handle_action(
                data_root,
                {"action": "jobs_list", "operation": "run_next", "job_types": ["requires_storage_reindex"]},
            )[1]
            failed_jobs = service.handle_action(data_root, {"action": "jobs_list", "status": "failed"})[1]

            with database.connect(data_root) as db:
                refs = [
                    database.row_payload(row) or {}
                    for row in db.execute("SELECT * FROM external_refs WHERE entity_id = ? ORDER BY node_id", (storage_file_id,))
                ]
                stale_claim_count = db.execute(
                    "SELECT COUNT(*) AS count FROM claims WHERE stale = 1 AND node_id IN (?, ?)",
                    (first["node"]["id"], second_node["id"]),
                ).fetchone()["count"]
                stale_chunk_count = db.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM source_chunks
                    WHERE json_extract(metadata_json, '$.staleness.state') = 'stale'
                    """,
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
            self.assertEqual(applied["reindex_job"]["job_type"], "requires_storage_reindex")
            self.assertEqual(len(ready_jobs["jobs"]), 1)
            self.assertEqual(ready_jobs["jobs"][0]["job_type"], "requires_storage_reindex")
            self.assertEqual(old_ingest_jobs["jobs"], [])
            self.assertTrue(reindex_run["ok"])
            self.assertEqual(reindex_run["job"]["status"], "done")
            self.assertEqual(reindex_run["result"]["status"], "requires_storage_reindex")
            self.assertTrue(reindex_run["result"]["action_required"])
            self.assertEqual(reindex_run["result"]["storage_identity"]["entity_id"], storage_file_id)
            self.assertEqual(reindex_run["result"]["reindex_suggestion"]["mcp_tool"], "storage_drive_index")
            self.assertEqual(failed_jobs["jobs"], [])
            self.assertGreaterEqual(stale_claim_count, 2)
            self.assertGreaterEqual(stale_chunk_count, 1)
            self.assertTrue(source_query["results"])
            self.assertEqual(source_query["results"][0]["freshness"], "stale")
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
