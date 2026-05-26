"""Tests for the Vault app contract and bundled frontend."""

from __future__ import annotations

from pathlib import Path
import json
import subprocess
import sys
import unittest
from unittest.mock import patch

from core.apps.contracts import parse_app_contract_file


APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

from agent_operations import handle_operation


def sample_need(*, user_action: str = "create_grant") -> dict[str, object]:
    value_state = "available_ungranted" if user_action == "create_grant" else "missing_or_unmatched"
    return {
        "app_id": "browser",
        "app_name": "Browser",
        "logical_name": "api-token",
        "human_label": "API token",
        "scope": {"type": "workspace", "label": "Workspace"},
        "recommended_grant": {
            "actions": ["app.backend"],
            "target_patterns": ["maverick://app.backend/backend"],
            "resource_type": None,
            "resource_id": None,
            "reason": "Allow browser to use api-token through backend.",
        },
        "value_state": value_state,
        "grant_state": "missing",
        "user_action": user_action,
        "credential_match": {
            "matched": user_action == "create_grant",
            "method": "exact_alias" if user_action == "create_grant" else "none",
            "confidence": "high" if user_action == "create_grant" else "none",
            "ambiguous": False,
            "candidate_count": 1 if user_action == "create_grant" else 0,
            "candidates": [
                {
                    "secret_id": "sec_123",
                    "alias": "api-token",
                    "label": "API token",
                    "status": "active",
                    "kind": "api_key",
                }
            ]
            if user_action == "create_grant"
            else [],
        },
    }


def sample_mail_app_managed_need() -> dict[str, object]:
    return {
        "app_id": "mail",
        "app_name": "Mail",
        "logical_name": "gmail-refresh-token",
        "human_label": "Gmail Refresh Token",
        "scope": {"type": "resource", "resource_type": "mail_connection", "resource_id": None, "label": "Mail Connection"},
        "recommended_grant": {
            "actions": ["app.backend"],
            "target_patterns": ["maverick://app.backend/backend", "maverick://app.backend/cli/mail"],
            "resource_type": "mail_connection",
            "resource_id": None,
            "reason": "Allow mail to use gmail-refresh-token after app setup.",
        },
        "value_state": "missing_or_unmatched",
        "grant_state": "missing",
        "user_action": "complete_app_setup",
        "credential_match": {
            "matched": False,
            "method": "none",
            "confidence": "none",
            "ambiguous": False,
            "candidate_count": 0,
            "candidates": [],
        },
        "app_managed": True,
    }


class VaultAppTest(unittest.TestCase):
    """Verify Vault stays a frontend over Core Secrets, not a secret owner."""

    def test_contract_is_credential_inbox_without_app_secret_permissions(self) -> None:
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
            self.assertIn("diagnose", payload["supported_operations"])
            self.assertIn("connection_issues", payload["supported_operations"])
            self.assertIn("plan_fix", payload["supported_operations"])
            self.assertIn("explain_issue", payload["supported_operations"])
            self.assertIn("apply_fix", payload["supported_operations"])
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
            input=json.dumps({"app_id": "vault", "workspace_id": "default", "tool_name": "maverick_vault", "arguments": {"action": "bad"}}),
            text=True,
            capture_output=True,
            check=True,
        )
        bad_tool = subprocess.run(
            [sys.executable, str(APP_ROOT / "mcp" / "server.py")],
            input=json.dumps({"app_id": "vault", "workspace_id": "default", "tool_name": "bad"}),
            text=True,
            capture_output=True,
            check=True,
        )

        self.assertGreaterEqual(json.loads(cli.stdout)["status_code"], 400)
        self.assertGreaterEqual(json.loads(mcp.stdout)["status_code"], 400)
        self.assertGreaterEqual(json.loads(bad_tool.stdout)["status_code"], 400)

    def test_agent_operations_are_redaction_safe_and_payload_oriented(self) -> None:
        payload = {
            "app_id": "vault",
            "workspace_id": "default",
            "arguments": {"action": "diagnose", "needs": [sample_need()]},
        }
        diagnosis = json.loads(
            subprocess.run(
                [sys.executable, str(APP_ROOT / "cli" / "app_cli.py")],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                check=True,
            ).stdout
        )
        issues = json.loads(
            subprocess.run(
                [sys.executable, str(APP_ROOT / "mcp" / "server.py")],
                input=json.dumps({**payload, "tool_name": "maverick_vault", "arguments": {"action": "connection_issues", "needs": [sample_need()]}}),
                text=True,
                capture_output=True,
                check=True,
            ).stdout
        )

        self.assertEqual(diagnosis["issue_count"], 1)
        self.assertEqual(issues["payload_kind"], "connection_issues")
        issue = diagnosis["issues"][0]
        self.assertIn("issue_id", issue)
        self.assertEqual(issue["severity"], "medium")
        self.assertEqual(issue["app"], {"id": "browser", "name": "Browser"})
        self.assertEqual(issue["logical_need"]["name"], "api-token")
        self.assertTrue(issue["credential_metadata"]["matched"])
        self.assertEqual(issue["value_state"], "available_ungranted")
        self.assertEqual(issue["grant_state"], "missing")
        self.assertEqual(issue["recommended_action"], "create_grant")
        rendered = json.dumps([diagnosis, issues])
        self.assertNotIn("raw_value", rendered)
        self.assertNotIn("super-secret", rendered)

    def test_agent_operations_reject_raw_values_in_chat_payloads(self) -> None:
        payload = handle_operation(
            {
                "app_id": "vault",
                "workspace_id": "default",
                "arguments": {"action": "diagnose", "raw_value": "super-secret"},
            },
            action="diagnose",
        )

        rendered = json.dumps(payload)
        self.assertEqual(payload["status_code"], 400)
        self.assertTrue(payload["needs_secure_input"])
        self.assertNotIn("raw_value", rendered)
        self.assertNotIn("super-secret", rendered)

    def test_plan_fix_for_missing_grant_produces_core_grant_create_step(self) -> None:
        payload = handle_operation(
            {
                "app_id": "vault",
                "workspace_id": "default",
                "arguments": {"action": "plan_fix", "app_id": "browser", "needs": [sample_need()]},
            },
            action="plan_fix",
        )

        self.assertEqual(payload["status"], "planned")
        self.assertFalse(payload["mutation_performed"])
        self.assertEqual(payload["steps"][0]["core_surface"], "core.secret_grants.create")
        self.assertEqual(payload["steps"][0]["arguments"]["secret_id"], "sec_123")
        self.assertNotIn("raw_value", json.dumps(payload))

        issue_id = payload["issue"]["issue_id"]
        issue_payload = handle_operation(
            {
                "app_id": "vault",
                "workspace_id": "default",
                "arguments": {"action": "plan_fix", "issue_id": issue_id, "issues": [payload["issue"]]},
            },
            action="plan_fix",
        )
        self.assertEqual(issue_payload["steps"][0]["core_surface"], "core.secret_grants.create")

    def test_explain_issue_produces_user_facing_non_technical_text(self) -> None:
        payload = handle_operation(
            {
                "app_id": "vault",
                "workspace_id": "default",
                "arguments": {"action": "explain_issue", "app_id": "browser", "needs": [sample_need()]},
            },
            action="explain_issue",
        )

        self.assertEqual(payload["status"], "explained")
        self.assertIn("Browser has a matching saved credential", payload["message"])
        self.assertNotIn("target_patterns", payload["message"])
        self.assertNotIn("maverick://", payload["message"])
        self.assertNotIn("grant_state", payload["message"])

    def test_apply_fix_without_confirmation_or_core_surface_does_not_mutate(self) -> None:
        unconfirmed = handle_operation(
            {
                "app_id": "vault",
                "workspace_id": "default",
                "arguments": {"action": "apply_fix", "app_id": "browser", "needs": [sample_need()]},
            },
            action="apply_fix",
        )
        with patch("agent_operations._core_cli_surface_available", return_value=False):
            unavailable = handle_operation(
                {
                    "app_id": "vault",
                    "workspace_id": "default",
                    "arguments": {
                        "action": "apply_fix",
                        "app_id": "browser",
                        "needs": [sample_need()],
                        "confirmation": "confirm_apply_fix",
                    },
                },
                action="apply_fix",
            )

        self.assertEqual(unconfirmed["status"], "confirmation_required")
        self.assertFalse(unconfirmed["mutation_performed"])
        self.assertEqual(unavailable["status"], "core_grant_surface_unavailable")
        self.assertFalse(unavailable["mutation_performed"])
        self.assertNotIn("raw_value", json.dumps([unconfirmed, unavailable]))

    def test_apply_fix_for_missing_value_requires_secure_input(self) -> None:
        payload = handle_operation(
            {
                "app_id": "vault",
                "workspace_id": "default",
                "arguments": {
                    "action": "apply_fix",
                    "app_id": "browser",
                    "needs": [sample_need(user_action="add_value")],
                    "confirmation": "confirm_apply_fix",
                },
            },
            action="apply_fix",
        )

        self.assertEqual(payload["status"], "needs_secure_input")
        self.assertTrue(payload["needs_secure_input"])
        self.assertFalse(payload["mutation_performed"])

    def test_app_managed_mail_refresh_token_plan_does_not_request_raw_value(self) -> None:
        payload = handle_operation(
            {
                "app_id": "vault",
                "workspace_id": "default",
                "arguments": {
                    "action": "plan_fix",
                    "app_id": "mail",
                    "needs": [sample_mail_app_managed_need()],
                },
            },
            action="plan_fix",
        )

        self.assertEqual(payload["status"], "planned")
        self.assertEqual(payload["steps"][0]["step_id"], "app_managed_secret_setup")
        self.assertFalse(payload["steps"][0]["needs_secure_input"])
        rendered = json.dumps(payload)
        self.assertNotIn("raw_value", rendered)
        self.assertNotIn("rt-secret-raw", rendered)

    def test_main_frontend_source_is_credential_inbox_and_connection_issues(self) -> None:
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
        self.assertIn("Credential Inbox", source)
        self.assertIn("Connection Issues", source)
        self.assertIn("ConnectionIssuesView", source)
        self.assertIn("GrantsView", source)
        self.assertIn("AuditView", source)
        self.assertIn("tab === 'advanced'", source)
        self.assertNotIn("Readiness issues", source)
        self.assertNotIn('label="Active grants"', source)
        self.assertNotIn('label="Review events"', source)
        self.assertNotIn("applyMetricFilter('active-grants'", source)
        self.assertNotIn("applyMetricFilter('review-events'", source)

    def test_connection_issues_view_hides_technical_details_by_default(self) -> None:
        source = (APP_ROOT / "frontend" / "src" / "components" / "ConnectionIssuesView.tsx").read_text(encoding="utf-8")

        self.assertIn("Connection Issues", source)
        self.assertIn("App", source)
        self.assertIn("Credential", source)
        self.assertIn("Severity", source)
        self.assertIn("User input", source)
        self.assertIn("Recommended action", source)
        self.assertIn("<details", source)
        self.assertIn("Technical details", source)

    def test_removed_central_tab_selector_has_no_dead_code(self) -> None:
        shared_source = (APP_ROOT / "frontend" / "src" / "components" / "VaultShared.tsx").read_text(encoding="utf-8")
        types_source = (APP_ROOT / "frontend" / "src" / "vaultTypes.ts").read_text(encoding="utf-8")

        self.assertNotIn("TabButton", shared_source)
        self.assertNotIn("TABS", types_source)

    def test_readiness_uses_resource_scoped_consumer_metadata(self) -> None:
        source = (APP_ROOT / "frontend" / "src" / "readiness.ts").read_text(encoding="utf-8")

        self.assertIn("resource_scoped", source)
        self.assertIn("continue;", source)
        self.assertIn("grantResourceMatches", source)
        self.assertIn("targetVariantsForResourceScope", source)
        self.assertIn("resourceScopedAppSecretTarget", source)

    def test_sidebar_frontend_keeps_only_guided_credential_forms(self) -> None:
        source = (APP_ROOT / "frontend" / "src" / "widgets" / "vault-sidebar" / "main.tsx").read_text(encoding="utf-8")

        self.assertIn("createSecret", source)
        self.assertIn("rotateSecret", source)
        self.assertIn("SecureSecretInput", source)
        self.assertIn("Add credential", source)
        self.assertIn("Rotate credential", source)
        self.assertIn("Credential Inbox", source)
        self.assertIn("Connection Issues", source)
        self.assertIn("Import", source)
        self.assertIn("Advanced", source)
        self.assertIn("Add value", source)
        self.assertIn("Ask agent to fix", source)
        self.assertIn("Review fix", source)
        self.assertNotIn("createGrant", source)
        self.assertNotIn("New Grant", source)
        self.assertNotIn("New grant", source)
        self.assertNotIn("logical_names", source)
        self.assertNotIn("App with declared secret", source)
        self.assertNotIn("Declared logical name", source)
        self.assertNotIn("GRANT_TARGET_MODES", source)
        self.assertNotIn("target_cli_command", source)
        self.assertNotIn("target_mcp_tool", source)
        self.assertNotIn("target_custom", source)
        self.assertNotIn("resource_type", source)
        self.assertNotIn("resource_id", source)
        self.assertNotIn("Workspace scope", source)
        self.assertNotIn("consumerAllowsResourceType", source)
        self.assertNotIn("already have current grants", source)
        self.assertNotIn("grantBlocksLogicalNameSelection", source)
        self.assertNotIn("disableSecret", source)
        self.assertNotIn("revokeSecret", source)
        self.assertNotIn("revokeGrant", source)
        self.assertNotIn("vault-sidebar-lifecycle", source)
        self.assertNotIn("Recent audit", source)
        self.assertNotIn('placeholder="logical-name"', source)

    def test_frontend_dist_calls_core_secret_api_without_raw_value_display_or_normal_grant_workflow(self) -> None:
        html = (APP_ROOT / "frontend" / "dist" / "index.html").read_text(encoding="utf-8")
        assets = sorted((APP_ROOT / "frontend" / "dist" / "assets").rglob("*.js"))
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
        self.assertIn("/api/secret-grant-needs", bundle)
        self.assertIn("raw_value", bundle)
        self.assertIn("Credential Inbox", bundle)
        self.assertIn("Connection Issues", bundle)
        self.assertIn("Import", bundle)
        self.assertIn("Advanced", bundle)
        self.assertIn("Add value", bundle)
        self.assertIn("Ask agent to fix", bundle)
        self.assertIn("Review fix", bundle)
        self.assertIn("Technical details", bundle)
        self.assertIn("Used by", bundle)
        self.assertIn("Last updated", bundle)
        self.assertNotIn("New Grant", bundle)
        self.assertNotIn("New grant", bundle)
        self.assertNotIn("GRANT_TARGET_MODES", bundle)
        self.assertNotIn("target_cli_command", bundle)
        self.assertNotIn("target_mcp_tool", bundle)
        self.assertNotIn("target_custom", bundle)
        self.assertNotIn("App with declared secret", bundle)
        self.assertNotIn("Declared logical name", bundle)
        self.assertNotIn("Workspace scope", bundle)
        self.assertNotIn("browser.autofill", bundle)
        self.assertNotIn("super-secret", bundle)
        self.assertNotIn("fixture-secret", bundle)
        self.assertNotIn("example-secret-value", bundle)
        self.assertNotIn("data/vault", bundle)
        self.assertTrue((APP_ROOT / "frontend" / "dist" / "widgets" / "vault-sidebar" / "index.html").exists())
        self.assertTrue((APP_ROOT / "frontend" / "dist" / "widgets" / "vault-sidebar-footer" / "index.html").exists())

    def test_frontend_sources_and_dist_have_no_native_prompts_or_browser_autofill(self) -> None:
        files = [
            *sorted((APP_ROOT / "frontend" / "src").rglob("*")),
            *sorted((APP_ROOT / "frontend" / "dist").rglob("*")),
        ]
        text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in files
            if path.is_file() and path.suffix in {".ts", ".tsx", ".js", ".html"}
        )

        self.assertNotIn("window.alert", text)
        self.assertNotIn("window.confirm", text)
        self.assertNotIn("browser.autofill", text)

    def test_core_secret_mutations_are_limited_to_controlled_frontend_flows(self) -> None:
        src_root = APP_ROOT / "frontend" / "src"
        api_source = (src_root / "api.ts").read_text(encoding="utf-8")
        create_hits = sorted(
            str(path.relative_to(src_root))
            for path in src_root.rglob("*")
            if path.is_file() and "createSecret" in path.read_text(encoding="utf-8")
        )
        rotate_hits = sorted(
            str(path.relative_to(src_root))
            for path in src_root.rglob("*")
            if path.is_file() and "rotateSecret" in path.read_text(encoding="utf-8")
        )

        self.assertEqual(create_hits, ["api.ts", "widgets/vault-sidebar-footer/main.tsx", "widgets/vault-sidebar/main.tsx"])
        self.assertEqual(rotate_hits, ["api.ts", "widgets/vault-sidebar/main.tsx"])
        self.assertNotIn("disableSecret", api_source)
        self.assertNotIn("revokeSecret", api_source)
        self.assertNotIn("createGrant", api_source)
        self.assertNotIn("revokeGrant", api_source)

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
