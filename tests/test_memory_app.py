"""Tests for the Memory app."""

from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest

from core.apps.contracts import parse_app_contract_file
from core.api.platform_state import bootstrap_platform_state
from core.cli.models import CliInvocationContext
from core.cli.service import run_core_cli_command
from core.mcp.models import McpInvocationContext
from core.mcp.service import call_mcp_tool
from core.shared.entrypoints import run_json_entrypoint


REPO_ROOT = Path(__file__).resolve().parents[1]
MEMORY_ROOT = REPO_ROOT / "apps" / "memory"


class MemoryAppTestCase(unittest.TestCase):
    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick-v3"
        for name in ("core", "apps", "workspaces", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        (repo_root / "IMPLEMENTATION_TASKLIST.md").write_text("", encoding="utf-8")
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

    def test_contract_declares_memory_surfaces_and_reference_entities(self) -> None:
        parsed = parse_app_contract_file(MEMORY_ROOT)

        self.assertEqual(parsed.app_id, "memory")
        self.assertEqual(parsed.contract.entrypoints.backend, "backend/app_backend.py")
        self.assertEqual(parsed.contract.entrypoints.frontend, "frontend/dist")
        self.assertIn("memory_context", parsed.contract.capabilities.mcp_tools)
        self.assertIn("memory_reference_manifest", parsed.contract.capabilities.mcp_tools)
        self.assertEqual(parsed.contract.capabilities.cli_commands, ["memory"])
        self.assertEqual(parsed.contract.storage.storage_kind, "sqlite+files")
        self.assertEqual(parsed.contract.capabilities.reference_entities[0].entity_type, "node")

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
            self.assertEqual(health["schema_version"], "1")

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

            self.assertEqual(backend["status_code"], 200)
            self.assertEqual(cli["status_code"], 200)
            self.assertTrue(cli["items"])
            self.assertEqual(mcp["app_id"], "memory")
            self.assertEqual(mcp["entity_types"][0]["entity_type"], "node")

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
