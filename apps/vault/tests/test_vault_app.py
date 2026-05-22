"""Tests for the Vault app contract and bundled frontend."""

from __future__ import annotations

from pathlib import Path
import json
import subprocess
import sys
import unittest

from core.apps.contracts import parse_app_contract_file


APP_ROOT = Path(__file__).resolve().parents[1]


class VaultAppTest(unittest.TestCase):
    """Verify Vault stays a frontend over Core Secrets, not a secret owner."""

    def test_contract_is_admin_frontend_without_app_secret_permissions(self) -> None:
        parsed = parse_app_contract_file(APP_ROOT)
        contract = parsed.contract

        self.assertEqual(parsed.app_id, "vault")
        self.assertEqual(contract.presentation.frontend_role, "workspace")
        self.assertEqual(contract.visibility.platform_roles, ["admin"])
        self.assertEqual(contract.permissions.secrets.read, [])
        self.assertEqual(contract.permissions.secrets.write, [])
        self.assertEqual(contract.entrypoints.backend, None)
        self.assertEqual(contract.entrypoints.frontend, "frontend/dist")
        self.assertEqual(contract.entrypoints.cli, "cli/app_cli.py")
        self.assertEqual(contract.entrypoints.mcp, "mcp/server.py")
        self.assertEqual(contract.entrypoints.skills_root, "skills")
        self.assertEqual(contract.capabilities.cli_commands, ["vault"])
        self.assertEqual(contract.capabilities.mcp_tools, ["maverick_vault"])
        self.assertEqual(contract.capabilities.skills, ["vault-ops"])
        self.assertEqual(contract.storage.storage_kind, "none")
        self.assertEqual(contract.storage.primary_paths, [])
        self.assertEqual([widget.widget_id for widget in contract.widgets], ["vault-sidebar", "vault-sidebar-footer"])
        self.assertTrue(all(widget.host == "base-shell" for widget in contract.widgets))
        self.assertTrue((APP_ROOT / "skills" / "vault-ops" / "SKILL.md").is_file())

    def test_cli_and_mcp_entrypoints_are_redaction_safe_manifests(self) -> None:
        cli = subprocess.run(
            [sys.executable, str(APP_ROOT / "cli" / "app_cli.py")],
            input=json.dumps({"app_id": "vault", "workspace_id": "default", "arguments": {"action": "manifest"}}),
            text=True,
            capture_output=True,
            check=True,
        )
        mcp = subprocess.run(
            [sys.executable, str(APP_ROOT / "mcp" / "server.py")],
            input=json.dumps({"app_id": "vault", "workspace_id": "default", "tool_name": "maverick_vault"}),
            text=True,
            capture_output=True,
            check=True,
        )

        payloads = [json.loads(cli.stdout), json.loads(mcp.stdout)]
        for payload in payloads:
            self.assertTrue(payload["redaction_safe"])
            self.assertFalse(payload["secret_values_available"])
            self.assertEqual(payload["core_secret_owner"], "core.secrets")
            self.assertIn("read_only", payload["core_surfaces"])
            self.assertIn("mutative_full_access", payload["core_surfaces"])
            self.assertIn("admin_http", payload["core_surfaces"])
            self.assertTrue(
                any(surface["path"] == "/api/secret-grants" for surface in payload["core_surfaces"]["admin_http"])
            )
            self.assertTrue(
                all("authority" in surface for surface in payload["core_surfaces"]["mutative_full_access"])
            )
            self.assertNotIn("raw_value", json.dumps(payload))

    def test_cli_and_mcp_reject_unsupported_operations(self) -> None:
        cli = subprocess.run(
            [sys.executable, str(APP_ROOT / "cli" / "app_cli.py")],
            input=json.dumps({"app_id": "vault", "workspace_id": "default", "arguments": {"action": "bad"}}),
            text=True,
            capture_output=True,
            check=True,
        )
        mcp = subprocess.run(
            [sys.executable, str(APP_ROOT / "mcp" / "server.py")],
            input=json.dumps({"app_id": "vault", "workspace_id": "default", "tool_name": "bad"}),
            text=True,
            capture_output=True,
            check=True,
        )

        self.assertGreaterEqual(json.loads(cli.stdout)["status_code"], 400)
        self.assertGreaterEqual(json.loads(mcp.stdout)["status_code"], 400)

    def test_main_frontend_source_is_read_only_governance(self) -> None:
        source = (APP_ROOT / "frontend" / "src" / "main.tsx").read_text(encoding="utf-8")

        self.assertNotIn("createSecret", source)
        self.assertNotIn("createGrant", source)
        self.assertNotIn("rotateSecret", source)
        self.assertNotIn("disableSecret", source)
        self.assertNotIn("revokeSecret", source)
        self.assertNotIn("raw_value", source)
        self.assertNotIn("vault-search", source)
        self.assertNotIn("vault-toolbar", source)
        self.assertNotIn("vault-tabs", source)
        self.assertIn("ReadinessView", source)

    def test_removed_central_tab_selector_has_no_dead_code(self) -> None:
        shared_source = (APP_ROOT / "frontend" / "src" / "components" / "VaultShared.tsx").read_text(encoding="utf-8")
        types_source = (APP_ROOT / "frontend" / "src" / "vaultTypes.ts").read_text(encoding="utf-8")

        self.assertNotIn("TabButton", shared_source)
        self.assertNotIn("TABS", types_source)

    def test_sidebar_frontend_keeps_only_guided_create_forms(self) -> None:
        source = (APP_ROOT / "frontend" / "src" / "widgets" / "vault-sidebar" / "main.tsx").read_text(encoding="utf-8")

        self.assertIn("createSecret", source)
        self.assertIn("createGrant", source)
        self.assertIn("listGrantTargets", source)
        self.assertIn("logical_names", source)
        self.assertIn("App with declared secret", source)
        self.assertIn("Declared logical name", source)
        self.assertIn("GRANT_TARGET_MODES", source)
        self.assertIn("target_cli_command", source)
        self.assertIn("target_mcp_tool", source)
        self.assertIn("already have current grants", source)
        self.assertIn("grantBlocksLogicalNameSelection", source)
        self.assertIn("grant.status !== 'active'", source)
        self.assertNotIn("rotateSecret", source)
        self.assertNotIn("disableSecret", source)
        self.assertNotIn("revokeSecret", source)
        self.assertNotIn("revokeGrant", source)
        self.assertNotIn("vault-sidebar-lifecycle", source)
        self.assertNotIn("Recent audit", source)
        self.assertNotIn('placeholder="logical-name"', source)

    def test_frontend_dist_calls_core_secret_api_without_raw_value_display(self) -> None:
        html = (APP_ROOT / "frontend" / "dist" / "index.html").read_text(encoding="utf-8")
        assets = sorted((APP_ROOT / "frontend" / "dist" / "assets").glob("*.js"))
        self.assertTrue(assets)
        bundle = "\n".join(path.read_text(encoding="utf-8") for path in assets)

        self.assertIn("Vault", html)
        self.assertNotIn('src="/assets/', html)
        self.assertNotIn('href="/assets/', html)
        self.assertIn('/apps/vault/assets/', html)
        self.assertIn("/api/secrets", bundle)
        self.assertIn("/api/secret-grants", bundle)
        self.assertIn("/api/secret-audit", bundle)
        self.assertIn("/api/secret-grant-targets", bundle)
        self.assertIn("expires_at", bundle)
        self.assertIn("raw_value", bundle)
        self.assertIn("maverick://app.backend/*", bundle)
        self.assertIn("maverick://app.backend/backend", bundle)
        self.assertIn("Readiness", bundle)
        self.assertNotIn("browser.autofill", bundle)
        self.assertNotIn("data/vault", bundle)
        self.assertTrue((APP_ROOT / "frontend" / "dist" / "widgets" / "vault-sidebar" / "index.html").exists())
        self.assertTrue((APP_ROOT / "frontend" / "dist" / "widgets" / "vault-sidebar-footer" / "index.html").exists())

    def test_sidebar_csv_import_has_guardrails(self) -> None:
        source = (APP_ROOT / "frontend" / "src" / "widgets" / "vault-sidebar-footer" / "main.tsx").read_text(encoding="utf-8")

        self.assertIn("MAX_CSV_BYTES", source)
        self.assertIn("MAX_IMPORT_ROWS", source)
        self.assertIn("ImportPreview", source)
        self.assertIn("newBatchId", source)
        self.assertIn("preflightImportRows", source)
        self.assertIn("SECRET_ID_PATTERN", source)
        self.assertIn("normalized secret id is invalid", source)
        self.assertIn("will_create", source)
        self.assertIn("Import selected", source)
        self.assertIn("Imported ${created} of ${rowsToCreate.length}", source)
        self.assertIn("failures", source)
        self.assertNotIn("window.confirm", source)
        self.assertNotIn("window.alert", source)


if __name__ == "__main__":
    unittest.main()
