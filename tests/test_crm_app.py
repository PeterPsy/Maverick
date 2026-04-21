"""Tests for the CRM app."""

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
CRM_ROOT = REPO_ROOT / "apps" / "crm"


class CrmAppTestCase(unittest.TestCase):
    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick-v3"
        for name in ("core", "apps", "workspaces", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        (repo_root / "IMPLEMENTATION_TASKLIST.md").write_text("", encoding="utf-8")
        for app_id in ("base-shell", "chat", "crm"):
            shutil.copytree(
                REPO_ROOT / "apps" / app_id,
                repo_root / "apps" / app_id,
                ignore=shutil.ignore_patterns("node_modules", "__pycache__"),
            )
        return repo_root

    def run_backend(self, data_root: Path, body: dict) -> dict:
        result = run_json_entrypoint(
            CRM_ROOT / "backend" / "app_backend.py",
            payload={"data_root": str(data_root), "body": body},
            cwd=CRM_ROOT,
        )
        self.assertIn("json", result)
        return result

    def test_contract_declares_forkable_crm_surfaces(self) -> None:
        parsed = parse_app_contract_file(CRM_ROOT)

        self.assertEqual(parsed.app_id, "crm")
        self.assertEqual(parsed.contract.distribution.mode, "source_available")
        self.assertEqual(parsed.contract.distribution.source_access, "forkable")
        self.assertEqual(parsed.contract.entrypoints.backend, "backend/app_backend.py")
        self.assertEqual(parsed.contract.entrypoints.frontend, "frontend/dist")
        self.assertIn("crm_reference_search", parsed.contract.capabilities.mcp_tools)
        self.assertEqual(parsed.contract.capabilities.cli_commands, ["crm"])
        self.assertEqual(parsed.contract.storage.storage_kind, "sqlite")
        self.assertEqual(
            [item.entity_type for item in parsed.contract.capabilities.reference_entities],
            ["account", "contact", "deal", "activity"],
        )

    def test_install_hook_is_idempotent_and_creates_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "crm"
            payload = {"data_root": str(data_root)}

            first = run_json_entrypoint(CRM_ROOT / "hooks" / "install.py", payload=payload, cwd=CRM_ROOT)
            second = run_json_entrypoint(CRM_ROOT / "hooks" / "install.py", payload=payload, cwd=CRM_ROOT)

            self.assertEqual(first["status"], "ok")
            self.assertEqual(second["status"], "ok")
            self.assertTrue((data_root / "crm.sqlite").is_file())
            health = run_json_entrypoint(CRM_ROOT / "hooks" / "health_check.py", payload=payload, cwd=CRM_ROOT)
            self.assertEqual(health["schema_version"], "1")

    def test_crm_end_to_end_searches_relationship_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "crm"
            account = self.run_backend(data_root, {"action": "create_account", "name": "Acme Spa", "domain": "acme.example", "status": "customer"})["json"]["account"]
            contact = self.run_backend(
                data_root,
                {
                    "action": "create_contact",
                    "account_id": account["id"],
                    "first_name": "Mario",
                    "last_name": "Rossi",
                    "email": "mario.rossi@acme.example",
                    "role": "Referente tecnico",
                },
            )["json"]["contact"]
            deal = self.run_backend(
                data_root,
                {
                    "action": "create_deal",
                    "account_id": account["id"],
                    "name": "Bando X",
                    "stage": "qualification",
                    "value": 25000,
                    "currency": "EUR",
                    "close_date": "2026-05-15",
                },
            )["json"]["deal"]
            activity = self.run_backend(
                data_root,
                {
                    "action": "add_activity",
                    "subject": "Allineamento tecnico bando X",
                    "body": "Mario Rossi conferma che mancano gli allegati economici.",
                    "account_id": account["id"],
                    "contact_id": contact["id"],
                    "deal_id": deal["id"],
                    "activity_type": "meeting",
                },
            )["json"]["activity"]
            relation = self.run_backend(
                data_root,
                {
                    "action": "link_entities",
                    "source_type": "contact",
                    "source_id": contact["id"],
                    "target_type": "deal",
                    "target_id": deal["id"],
                    "kind": "influences",
                    "strength": 0.8,
                    "reason": "Mario Rossi guida la validazione tecnica.",
                },
            )["json"]["relationship"]
            search = self.run_backend(data_root, {"action": "search", "query": "Mario Rossi bando X"})["json"]
            resolved = self.run_backend(data_root, {"action": "references.resolve", "entity_type": "deal", "entity_id": deal["id"]})["json"]
            summary = self.run_backend(data_root, {"action": "references.summarize", "entity_type": "activity", "entity_id": activity["id"]})["json"]

            self.assertEqual(account["name"], "Acme Spa")
            self.assertEqual(contact["display_name"], "Mario Rossi")
            self.assertEqual(deal["name"], "Bando X")
            self.assertEqual(activity["deal_id"], deal["id"])
            self.assertEqual(relation["kind"], "influences")
            self.assertTrue(any(item["title"] == "Mario Rossi" for item in search["results"]))
            self.assertTrue(resolved["exists"])
            self.assertEqual(resolved["title"], "Bando X")
            self.assertIn("allegati economici", summary["summary"])

    def test_backend_cli_and_mcp_entrypoints_share_crm_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "crm"
            backend = run_json_entrypoint(
                CRM_ROOT / "backend" / "app_backend.py",
                payload={"data_root": str(data_root), "body": {"action": "create_account", "name": "Acme Spa"}},
                cwd=CRM_ROOT,
            )
            cli = run_json_entrypoint(
                CRM_ROOT / "cli" / "app_cli.py",
                payload={"workspace_id": "default", "app_id": "crm", "data_root": str(data_root), "command_id": "app.crm.crm", "arguments": {"action": "search", "query": "Acme"}},
                cwd=CRM_ROOT,
            )
            mcp = run_json_entrypoint(
                CRM_ROOT / "mcp" / "server.py",
                payload={"workspace_id": "default", "app_id": "crm", "data_root": str(data_root), "tool_name": "crm_reference_manifest", "arguments": {}},
                cwd=CRM_ROOT,
            )

            self.assertEqual(backend["status_code"], 200)
            self.assertEqual(cli["status_code"], 200)
            self.assertTrue(cli["results"])
            self.assertEqual(mcp["app_id"], "crm")
            self.assertEqual(mcp["entity_types"][0]["entity_type"], "account")

    def test_core_mounted_cli_and_mcp_can_use_crm(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        cli_context = CliInvocationContext(caller_kind="sandbox_agent", workspace_id="default", agent_id="agent-1", effective_mode="sandbox")
        mcp_context = McpInvocationContext(caller_kind="sandbox_agent", workspace_id="default", agent_id="agent-1", effective_mode="sandbox")

        created = run_core_cli_command(
            command_id="app.crm.crm",
            context=cli_context,
            app_store=state.app_store,
            workspace_store=state.workspace_store,
            workspace_id="default",
            start_path=repo_root,
            arguments={"action": "create_account", "name": "Acme Spa", "industry": "Manufacturing"},
        )
        references = call_mcp_tool(
            tool_name="app.crm.crm_reference_search",
            context=mcp_context,
            app_store=state.app_store,
            workspace_id="default",
            start_path=repo_root,
            arguments={"query": "Acme"},
        )

        self.assertEqual(created["status_code"], 200)
        self.assertEqual(created["account"]["name"], "Acme Spa")
        self.assertEqual(references["status_code"], 200)
        self.assertEqual(references["results"][0]["entity_type"], "account")


if __name__ == "__main__":
    unittest.main()
