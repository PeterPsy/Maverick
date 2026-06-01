"""Tests for the core secret HTTP API used by Vault."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json

from core.api.secret_grant_needs import APP_WRITE_GRANT_REASON
from core.identity.service import create_user
from core.secrets.app_delivery import app_secret_target
from core.secrets.service import build_secret_ref, create_platform_secret, grant_app_secret_use, revoke_app_secret_grant
from core.workspaces.service import ensure_workspace_membership
from tests.unit.api.secret_api_test_support import SecretApiTestSupport


class SecretApiTestCase(SecretApiTestSupport):
    """Verify Vault-facing secret APIs are redaction-safe and policy-gated."""

    def test_secret_api_never_returns_raw_value(self) -> None:
        app = self.make_app()
        cookie = self.login(app)

        create_status, create_payload, _ = self.invoke(
            app,
            path="/api/secrets",
            method="POST",
            cookie=cookie,
            body={"label": "Example", "alias": "example-login", "raw_value": "super-secret", "kind": "password"},
        )
        list_status, list_payload, _ = self.invoke(app, path="/api/secrets", cookie=cookie)

        self.assertEqual(create_status, 201)
        self.assertEqual(list_status, 200)
        encoded = json.dumps([create_payload, list_payload], default=str)
        self.assertNotIn("super-secret", encoded)
        self.assertNotIn("raw_value", encoded)
        self.assertEqual(create_payload["secret"]["kind"], "password")

    def test_secret_create_rejects_unknown_kind(self) -> None:
        app = self.make_app()
        cookie = self.login(app)

        status, payload, _ = self.invoke(
            app,
            path="/api/secrets",
            method="POST",
            cookie=cookie,
            body={"label": "Example", "raw_value": "super-secret", "kind": "unknown"},
        )

        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "secret_error")

    def test_secret_metadata_update_never_returns_raw_value(self) -> None:
        app = self.make_app()
        cookie = self.login(app)
        _create_status, create_payload, _ = self.invoke(
            app,
            path="/api/secrets",
            method="POST",
            cookie=cookie,
            body={"label": "Example", "alias": "example-login", "raw_value": "super-secret", "kind": "password"},
        )

        status, payload, _ = self.invoke(
            app,
            path=f"/api/secrets/{create_payload['secret']['secret_id']}",
            method="PATCH",
            cookie=cookie,
            body={
                "label": "Updated Example",
                "alias": "updated-login",
                "description": "Used by the agent",
                "kind": "api_key",
            },
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["secret"]["label"], "Updated Example")
        self.assertEqual(payload["secret"]["alias"], "updated-login")
        self.assertEqual(payload["secret"]["description"], "Used by the agent")
        self.assertEqual(payload["secret"]["kind"], "api_key")
        encoded = json.dumps(payload, default=str)
        self.assertNotIn("super-secret", encoded)
        self.assertNotIn("raw_value", encoded)

    def test_grant_use_returns_redacted_lease_and_audit(self) -> None:
        app = self.make_app()
        cookie = self.login(app)
        _status, secret_payload, _ = self.invoke(
            app,
            path="/api/secrets",
            method="POST",
            cookie=cookie,
            body={"label": "Browser Login", "alias": "browser-login", "raw_value": "browser-secret"},
        )
        self.enable_workspace_app(app)
        grant_status, grant_payload, _ = self.invoke(
            app,
            path="/api/secret-grants",
            method="POST",
            cookie=cookie,
            body={
                "app_id": "browser",
                "logical_name": "login",
                "secret_id": secret_payload["secret"]["secret_id"],
                "actions": ["browser.autofill"],
                "target_patterns": ["https://example.com/*"],
                "expires_at": (datetime.now(tz=UTC) + timedelta(hours=1)).isoformat(),
            },
        )
        use_status, use_payload, _ = self.invoke(
            app,
            path="/api/secret-use",
            method="POST",
            cookie=cookie,
            body={
                "app_id": "browser",
                "grant_id": grant_payload["grant"]["grant_id"],
                "action": "browser.autofill",
                "target": "https://example.com/login",
            },
        )
        audit_status, audit_payload, _ = self.invoke(app, path="/api/secret-audit", cookie=cookie)

        self.assertEqual(grant_status, 201)
        self.assertEqual(use_status, 200)
        self.assertEqual(audit_status, 200)
        encoded = json.dumps([use_payload, audit_payload], default=str)
        self.assertIn("redacted_value", use_payload["lease"])
        self.assertIsNotNone(grant_payload["grant"]["expires_at"])
        self.assertNotIn("browser-secret", encoded)

    def test_grant_create_rejects_unknown_or_disabled_app(self) -> None:
        app = self.make_app()
        cookie = self.login(app)
        _status, secret_payload, _ = self.invoke(
            app,
            path="/api/secrets",
            method="POST",
            cookie=cookie,
            body={"label": "Browser Login", "raw_value": "browser-secret"},
        )

        status, payload, _ = self.invoke(
            app,
            path="/api/secret-grants",
            method="POST",
            cookie=cookie,
            body={
                "app_id": "browser",
                "logical_name": "login",
                "secret_id": secret_payload["secret"]["secret_id"],
                "actions": ["browser.autofill"],
                "target_patterns": ["https://example.com/*"],
            },
        )

        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "secret_error")

    def test_grant_create_rejects_inactive_secret_and_logical_conflict(self) -> None:
        app = self.make_app()
        cookie = self.login(app)
        self.enable_workspace_app(app)
        _status, secret_payload, _ = self.invoke(
            app,
            path="/api/secrets",
            method="POST",
            cookie=cookie,
            body={"label": "Browser Login", "raw_value": "browser-secret"},
        )
        first_status, _first_payload, _ = self.invoke(
            app,
            path="/api/secret-grants",
            method="POST",
            cookie=cookie,
            body={
                "app_id": "browser",
                "logical_name": "login",
                "secret_id": secret_payload["secret"]["secret_id"],
                "actions": ["browser.autofill"],
                "target_patterns": ["https://example.com/*"],
            },
        )
        conflict_status, conflict_payload, _ = self.invoke(
            app,
            path="/api/secret-grants",
            method="POST",
            cookie=cookie,
            body={
                "app_id": "browser",
                "logical_name": "login",
                "secret_id": secret_payload["secret"]["secret_id"],
                "actions": ["browser.autofill"],
                "target_patterns": ["https://example.com/*"],
            },
        )
        self.invoke(app, path=f"/api/secrets/{secret_payload['secret']['secret_id']}/disable", method="POST", cookie=cookie, body={})
        inactive_status, inactive_payload, _ = self.invoke(
            app,
            path="/api/secret-grants",
            method="POST",
            cookie=cookie,
            body={
                "app_id": "browser",
                "logical_name": "login-after-disable",
                "secret_id": secret_payload["secret"]["secret_id"],
                "actions": ["browser.autofill"],
                "target_patterns": ["https://example.com/*"],
            },
        )

        self.assertEqual(first_status, 201)
        self.assertEqual(conflict_status, 400)
        self.assertEqual(conflict_payload["error"], "secret_error")
        self.assertEqual(inactive_status, 400)
        self.assertEqual(inactive_payload["error"], "secret_error")

    def test_disable_secret_revokes_linked_grants(self) -> None:
        app = self.make_app()
        cookie = self.login(app)
        self.enable_workspace_app(app)
        _status, secret_payload, _ = self.invoke(
            app,
            path="/api/secrets",
            method="POST",
            cookie=cookie,
            body={"label": "Browser Login", "raw_value": "browser-secret"},
        )
        _grant_status, grant_payload, _ = self.invoke(
            app,
            path="/api/secret-grants",
            method="POST",
            cookie=cookie,
            body={
                "app_id": "browser",
                "logical_name": "login",
                "secret_id": secret_payload["secret"]["secret_id"],
                "actions": ["browser.autofill"],
                "target_patterns": ["https://example.com/*"],
            },
        )

        disable_status, disable_payload, _ = self.invoke(
            app,
            path=f"/api/secrets/{secret_payload['secret']['secret_id']}/disable",
            method="POST",
            cookie=cookie,
            body={},
        )
        grant_status, fetched_grant, _ = self.invoke(
            app,
            path=f"/api/secret-grants/{grant_payload['grant']['grant_id']}",
            cookie=cookie,
        )

        self.assertEqual(disable_status, 200)
        self.assertEqual(disable_payload["revoked_grant_count"], 1)
        self.assertEqual(grant_status, 200)
        self.assertEqual(fetched_grant["grant"]["status"], "revoked")

    def test_disable_secret_records_cascade_audit_for_each_grant_workspace(self) -> None:
        app = self.make_app()
        cookie = self.login(app)
        secret = create_platform_secret(app.state.secret_store, label="Shared Secret", raw_value="shared-secret")
        default_grant = grant_app_secret_use(
            app.state.secret_store,
            workspace_id="default",
            app_id="browser",
            logical_name="login",
            secret_ref=build_secret_ref(secret_id=secret.secret_id),
            actions=["browser.autofill"],
            target_patterns=["https://example.com/*"],
        )
        acme_grant = grant_app_secret_use(
            app.state.secret_store,
            workspace_id="acme",
            app_id="browser",
            logical_name="login",
            secret_ref=build_secret_ref(secret_id=secret.secret_id),
            actions=["browser.autofill"],
            target_patterns=["https://example.com/*"],
        )

        status, payload, _ = self.invoke(
            app,
            path=f"/api/secrets/{secret.secret_id}/disable",
            method="POST",
            cookie=cookie,
            body={},
        )

        cascade_audit = [
            item
            for item in app.state.observability_store.list_audit(source_domain="secrets")
            if item.action == "core.secrets.grant.revoke.cascade"
        ]
        self.assertEqual(status, 200)
        self.assertEqual(payload["revoked_grant_count"], 2)
        self.assertEqual({item.workspace_id for item in cascade_audit}, {"default", "acme"})
        self.assertEqual({item.payload["grant_id"] for item in cascade_audit}, {default_grant.grant_id, acme_grant.grant_id})

    def test_app_backend_grant_requires_deliverable_target_pattern(self) -> None:
        app = self.make_app()
        cookie = self.login(app)
        self.enable_workspace_app(app, secret_read=["api-token"], backend=True)
        _status, secret_payload, _ = self.invoke(
            app,
            path="/api/secrets",
            method="POST",
            cookie=cookie,
            body={"label": "Backend Token", "raw_value": "backend-secret"},
        )

        rejected_status, rejected_payload, _ = self.invoke(
            app,
            path="/api/secret-grants",
            method="POST",
            cookie=cookie,
            body={
                "app_id": "browser",
                "logical_name": "api-token",
                "secret_id": secret_payload["secret"]["secret_id"],
                "actions": ["app.backend"],
                "target_patterns": ["https://example.com/*"],
            },
        )
        accepted_status, accepted_payload, _ = self.invoke(
            app,
            path="/api/secret-grants",
            method="POST",
            cookie=cookie,
            body={
                "app_id": "browser",
                "logical_name": "api-token",
                "secret_id": secret_payload["secret"]["secret_id"],
                "actions": ["app.backend"],
                "target_patterns": ["maverick://app.backend/*"],
            },
        )

        self.assertEqual(rejected_status, 400)
        self.assertEqual(rejected_payload["error"], "secret_error")
        self.assertEqual(accepted_status, 201)
        self.assertEqual(accepted_payload["grant"]["target_patterns"], ["maverick://app.backend/*"])

    def test_app_backend_grant_requires_declared_logical_name(self) -> None:
        app = self.make_app()
        cookie = self.login(app)
        self.enable_workspace_app(app, secret_read=["declared-token"], backend=True)
        _status, secret_payload, _ = self.invoke(
            app,
            path="/api/secrets",
            method="POST",
            cookie=cookie,
            body={"label": "Backend Token", "raw_value": "backend-secret"},
        )

        rejected_status, rejected_payload, _ = self.invoke(
            app,
            path="/api/secret-grants",
            method="POST",
            cookie=cookie,
            body={
                "app_id": "browser",
                "logical_name": "missing-token",
                "secret_id": secret_payload["secret"]["secret_id"],
                "actions": ["app.backend"],
                "target_patterns": ["maverick://app.backend/*"],
            },
        )
        accepted_status, accepted_payload, _ = self.invoke(
            app,
            path="/api/secret-grants",
            method="POST",
            cookie=cookie,
            body={
                "app_id": "browser",
                "logical_name": "declared-token",
                "secret_id": secret_payload["secret"]["secret_id"],
                "actions": ["app.backend"],
                "target_patterns": ["maverick://app.backend/*"],
            },
        )

        self.assertEqual(rejected_status, 400)
        self.assertEqual(rejected_payload["error"], "secret_error")
        self.assertIn("does not declare", rejected_payload["detail"])
        self.assertEqual(accepted_status, 201)
        self.assertEqual(accepted_payload["grant"]["logical_name"], "declared-token")

    def test_app_backend_grants_allow_distinct_declared_targets_for_same_logical_name(self) -> None:
        app = self.make_app()
        cookie = self.login(app)
        self.enable_workspace_app(app, secret_read=["api-token"], backend=True, cli_commands=["sync"])
        app_root = app.state.repository_root / "apps" / "browser"
        (app_root / "cli").mkdir(parents=True, exist_ok=True)
        (app_root / "cli" / "command_schemas.json").write_text(
            json.dumps({"commands": {"sync": {"required_secrets": ["api-token"]}}}),
            encoding="utf-8",
        )
        _status, secret_payload, _ = self.invoke(
            app,
            path="/api/secrets",
            method="POST",
            cookie=cookie,
            body={"label": "Backend Token", "raw_value": "backend-secret"},
        )

        backend_status, _backend_payload, _ = self.invoke(
            app,
            path="/api/secret-grants",
            method="POST",
            cookie=cookie,
            body={
                "app_id": "browser",
                "logical_name": "api-token",
                "secret_id": secret_payload["secret"]["secret_id"],
                "actions": ["app.backend"],
                "target_patterns": ["maverick://app.backend/backend"],
            },
        )
        cli_status, cli_payload, _ = self.invoke(
            app,
            path="/api/secret-grants",
            method="POST",
            cookie=cookie,
            body={
                "app_id": "browser",
                "logical_name": "api-token",
                "secret_id": secret_payload["secret"]["secret_id"],
                "actions": ["app.backend"],
                "target_patterns": ["maverick://app.backend/cli/sync"],
            },
        )
        duplicate_status, duplicate_payload, _ = self.invoke(
            app,
            path="/api/secret-grants",
            method="POST",
            cookie=cookie,
            body={
                "app_id": "browser",
                "logical_name": "api-token",
                "secret_id": secret_payload["secret"]["secret_id"],
                "actions": ["app.backend"],
                "target_patterns": ["maverick://app.backend/backend"],
            },
        )
        wildcard_status, wildcard_payload, _ = self.invoke(
            app,
            path="/api/secret-grants",
            method="POST",
            cookie=cookie,
            body={
                "app_id": "browser",
                "logical_name": "api-token",
                "secret_id": secret_payload["secret"]["secret_id"],
                "actions": ["app.backend"],
                "target_patterns": ["maverick://app.backend/*"],
            },
        )

        self.assertEqual(backend_status, 201)
        self.assertEqual(cli_status, 201)
        self.assertEqual(cli_payload["grant"]["target_patterns"], ["maverick://app.backend/cli/sync"])
        self.assertEqual(duplicate_status, 400)
        self.assertIn("overlapping targets", duplicate_payload["detail"])
        self.assertEqual(wildcard_status, 400)
        self.assertIn("overlapping targets", wildcard_payload["detail"])

    def test_app_backend_grant_rejects_targets_without_required_secret_consumer(self) -> None:
        app = self.make_app()
        cookie = self.login(app)
        self.enable_workspace_app(app, secret_read=["api-token"], cli_commands=["sync"])
        app_root = app.state.repository_root / "apps" / "browser"
        (app_root / "cli").mkdir(parents=True, exist_ok=True)
        (app_root / "cli" / "command_schemas.json").write_text(
            json.dumps({"commands": {"sync": {"required_secrets": ["api-token"]}}}),
            encoding="utf-8",
        )
        _status, secret_payload, _ = self.invoke(
            app,
            path="/api/secrets",
            method="POST",
            cookie=cookie,
            body={"label": "Backend Token", "raw_value": "backend-secret"},
        )

        rejected_status, rejected_payload, _ = self.invoke(
            app,
            path="/api/secret-grants",
            method="POST",
            cookie=cookie,
            body={
                "app_id": "browser",
                "logical_name": "api-token",
                "secret_id": secret_payload["secret"]["secret_id"],
                "actions": ["app.backend"],
                "target_patterns": ["maverick://app.backend/cli/noop"],
            },
        )

        self.assertEqual(rejected_status, 400)
        self.assertEqual(rejected_payload["error"], "secret_error")
        self.assertIn("does not declare a secret consumer", rejected_payload["detail"])

    def test_expired_grants_are_reported_and_do_not_block_replacement(self) -> None:
        app = self.make_app()
        cookie = self.login(app)
        self.enable_workspace_app(app, secret_read=["api-token"], backend=True)
        secret = create_platform_secret(app.state.secret_store, label="Backend Token", raw_value="backend-secret")
        expired = grant_app_secret_use(
            app.state.secret_store,
            workspace_id="default",
            app_id="browser",
            logical_name="api-token",
            secret_ref=build_secret_ref(secret_id=secret.secret_id),
            actions=["app.backend"],
            target_patterns=["maverick://app.backend/*"],
            expires_at=datetime.now(tz=UTC) - timedelta(minutes=1),
        )

        list_status, list_payload, _ = self.invoke(app, path="/api/secret-grants", cookie=cookie)
        create_status, create_payload, _ = self.invoke(
            app,
            path="/api/secret-grants",
            method="POST",
            cookie=cookie,
            body={
                "app_id": "browser",
                "logical_name": "api-token",
                "secret_id": secret.secret_id,
                "actions": ["app.backend"],
                "target_patterns": ["maverick://app.backend/*"],
            },
        )

        listed = {item["grant_id"]: item for item in list_payload["items"]}
        self.assertEqual(list_status, 200)
        self.assertEqual(listed[expired.grant_id]["effective_status"], "expired")
        self.assertEqual(create_status, 201)
        self.assertEqual(create_payload["grant"]["logical_name"], "api-token")

    def test_secret_grant_targets_are_admin_specific_and_not_in_app_registry(self) -> None:
        app = self.make_app()
        cookie = self.login(app)
        self.enable_workspace_app(app, secret_read=["api-token", "webhook-token"], backend=True)

        registry_status, registry_payload, _ = self.invoke(app, path="/api/apps", cookie=cookie)
        targets_status, targets_payload, _ = self.invoke(app, path="/api/secret-grant-targets", cookie=cookie)

        self.assertEqual(registry_status, 200)
        self.assertEqual(targets_status, 200)
        self.assertNotIn("permissions", json.dumps(registry_payload))
        target = next(item for item in targets_payload["items"] if item["app_id"] == "browser")
        self.assertEqual(target["logical_names"], ["api-token", "webhook-token"])
        self.assertIn("surfaces", target)
        self.assertIn("backend", target["surfaces"])
        self.assertIn("cli_commands", target["surfaces"])
        self.assertIn("mcp_tools", target["surfaces"])

    def test_secret_grant_targets_report_only_cli_mcp_required_secret_consumers(self) -> None:
        app = self.make_app()
        cookie = self.login(app)
        self.enable_workspace_app(
            app,
            secret_read=["api-token", "webhook-token", "unused-token"],
            cli_commands=["sync", "noop"],
            mcp_tools=["send"],
        )
        app_root = app.state.repository_root / "apps" / "browser"
        (app_root / "cli").mkdir(parents=True, exist_ok=True)
        (app_root / "mcp").mkdir(parents=True, exist_ok=True)
        (app_root / "cli" / "command_schemas.json").write_text(
            json.dumps({"commands": {"sync": {"required_secrets": ["api-token"]}, "noop": {}}}),
            encoding="utf-8",
        )
        (app_root / "mcp" / "tool_schemas.json").write_text(
            json.dumps({"tools": {"send": {"required_secrets": ["webhook-token"]}}}),
            encoding="utf-8",
        )

        targets_status, targets_payload, _ = self.invoke(app, path="/api/secret-grant-targets", cookie=cookie)

        self.assertEqual(targets_status, 200)
        target = next(item for item in targets_payload["items"] if item["app_id"] == "browser")
        self.assertEqual(target["logical_names"], ["api-token", "webhook-token"])
        self.assertEqual(
            target["consumers"],
            {
                "api-token": {
                    "backend": False,
                    "cli_commands": ["sync"],
                    "mcp_tools": [],
                    "resource_scoped": False,
                    "resource_types": [],
                },
                "webhook-token": {
                    "backend": False,
                    "cli_commands": [],
                    "mcp_tools": ["send"],
                    "resource_scoped": False,
                    "resource_types": [],
                },
            },
        )
        self.assertFalse(target["surfaces"]["backend"])
        self.assertEqual(target["surfaces"]["cli_commands"], ["sync"])
        self.assertEqual(target["surfaces"]["mcp_tools"], ["send"])

    def test_secret_grant_targets_report_resource_scoped_selector_metadata(self) -> None:
        app = self.make_app()
        cookie = self.login(app)
        self.enable_workspace_app(
            app,
            secret_read=["client-secret", "refresh-token"],
            cli_commands=["sync"],
            mcp_tools=["thread.get"],
        )
        app_root = app.state.repository_root / "apps" / "browser"
        (app_root / "cli").mkdir(parents=True, exist_ok=True)
        (app_root / "mcp").mkdir(parents=True, exist_ok=True)
        non_resource_selector = {
            "required_secrets": ["client-secret"],
            "resource_lookup": {"kind": "connection_from_arguments"},
        }
        resource_selector = {
            "required_secrets": ["refresh-token"],
            "resource_type": "mail_connection",
            "resource_lookup": {"kind": "connection_from_arguments"},
        }
        (app_root / "cli" / "command_schemas.json").write_text(
            json.dumps({"commands": {"sync": {"secret_selectors": [non_resource_selector, resource_selector]}}}),
            encoding="utf-8",
        )
        (app_root / "mcp" / "tool_schemas.json").write_text(
            json.dumps({"tools": {"thread.get": {"secret_selectors": [resource_selector]}}}),
            encoding="utf-8",
        )

        targets_status, targets_payload, _ = self.invoke(app, path="/api/secret-grant-targets", cookie=cookie)

        self.assertEqual(targets_status, 200)
        target = next(item for item in targets_payload["items"] if item["app_id"] == "browser")
        self.assertEqual(target["consumers"]["client-secret"]["resource_scoped"], False)
        self.assertEqual(target["consumers"]["client-secret"]["resource_types"], [])
        self.assertEqual(target["consumers"]["refresh-token"]["resource_scoped"], True)
        self.assertEqual(target["consumers"]["refresh-token"]["resource_types"], ["mail_connection"])
        self.assertEqual(target["consumers"]["refresh-token"]["cli_commands"], ["sync"])
        self.assertEqual(target["consumers"]["refresh-token"]["mcp_tools"], ["thread.get"])

    def test_secret_grant_needs_use_app_provided_resource_inventory(self) -> None:
        app = self.make_app()
        cookie = self.login(app)
        self.enable_workspace_app(
            app,
            app_id="mail",
            secret_read=["mailbox-password"],
            cli_commands=["mail"],
        )
        app_root = app.state.repository_root / "apps" / "mail"
        contract_path = app_root / "app_contract.json"
        contract_payload = json.loads(contract_path.read_text(encoding="utf-8"))
        contract_payload["entrypoints"]["cli"] = "cli/app_cli.py"
        contract_path.write_text(json.dumps(contract_payload, indent=2), encoding="utf-8")
        (app_root / "cli").mkdir(parents=True, exist_ok=True)
        (app_root / "cli" / "command_schemas.json").write_text(
            json.dumps(
                {
                    "commands": {
                        "mail": {
                            "secret_resource_inventory": True,
                            "secret_selectors": [
                                {
                                    "required_secrets": ["mailbox-password"],
                                    "resource_type": "mail_connection",
                                    "resource_lookup": {"kind": "mail_connection_from_arguments"},
                                }
                            ]
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        (app_root / "cli" / "app_cli.py").write_text(
            "import json, sys\n"
            "payload = json.loads(sys.stdin.read() or '{}')\n"
            "if payload.get('surface') == 'secret_resource_inventory':\n"
            "    json.dump({'resources': [\n"
            "        {'logical_name': 'mailbox-password', 'resource_type': 'mail_connection', 'resource_id': 'mail_connection_imap_team-loopino.ai', 'label': 'team@loopino.ai mailbox'}\n"
            "    ]}, sys.stdout)\n"
            "else:\n"
            "    json.dump({'ok': True}, sys.stdout)\n",
            encoding="utf-8",
        )

        status, payload, _ = self.invoke(app, path="/api/secret-grant-needs", cookie=cookie)

        self.assertEqual(status, 200)
        need = next(item for item in payload["items"] if item["app_id"] == "mail" and item["logical_name"] == "mailbox-password")
        self.assertEqual(
            need["scope"],
            {
                "type": "resource",
                "resource_type": "mail_connection",
                "resource_id": "mail_connection_imap_team-loopino.ai",
                "label": "team@loopino.ai mailbox",
            },
        )
        self.assertEqual(need["recommended_grant"]["resource_type"], "mail_connection")
        self.assertEqual(need["recommended_grant"]["resource_id"], "mail_connection_imap_team-loopino.ai")
        self.assertIn(
            app_secret_target("cli/mail", resource_type="mail_connection", resource_id="mail_connection_imap_team-loopino.ai"),
            need["recommended_grant"]["target_patterns"],
        )

    def test_secret_grant_needs_recommend_workspace_scoped_spec_from_descriptors(self) -> None:
        app = self.make_app()
        cookie = self.login(app)
        self.enable_workspace_app(app, secret_read=["api-token"], backend=True, cli_commands=["sync"])
        app_root = app.state.repository_root / "apps" / "browser"
        (app_root / "cli").mkdir(parents=True, exist_ok=True)
        (app_root / "cli" / "command_schemas.json").write_text(
            json.dumps({"commands": {"sync": {"required_secrets": ["api-token"]}}}),
            encoding="utf-8",
        )

        status, payload, _ = self.invoke(app, path="/api/secret-grant-needs", cookie=cookie)

        self.assertEqual(status, 200)
        need = next(item for item in payload["items"] if item["app_id"] == "browser" and item["logical_name"] == "api-token")
        self.assertEqual(need["scope"], {"type": "workspace", "label": "Workspace"})
        self.assertEqual(need["recommended_grant"]["actions"], ["app.backend"])
        self.assertEqual(
            need["recommended_grant"]["target_patterns"],
            [app_secret_target("backend"), app_secret_target("cli/sync")],
        )
        self.assertEqual(need["recommended_grant"]["resource_type"], None)
        self.assertEqual(need["recommended_grant"]["resource_id"], None)
        self.assertEqual(need["value_state"], "missing_or_unmatched")
        self.assertEqual(need["grant_state"], "missing")
        self.assertEqual(need["user_action"], "add_value")

    def test_secret_grant_targets_include_issue_needs_for_existing_endpoint(self) -> None:
        app = self.make_app()
        cookie = self.login(app)
        self.enable_workspace_app(app, secret_read=["api-token"], backend=True)

        status, payload, _ = self.invoke(app, path="/api/secret-grant-targets", cookie=cookie)

        self.assertEqual(status, 200)
        self.assertIn("items", payload)
        self.assertIn("needs", payload)
        self.assertTrue(any(item["logical_name"] == "api-token" for item in payload["needs"]))

    def test_secret_grant_needs_recommend_resource_scoped_selector_spec_and_app_managed_state(self) -> None:
        app = self.make_app()
        cookie = self.login(app)
        self._enable_mail_app_with_resource_secret(app)
        secret = create_platform_secret(
            app.state.secret_store,
            label="mail gmail-refresh-token",
            raw_value="refresh-token",
            alias="default-mail-gmail-refresh-token-mail_connection-conn_1",
            secret_id="app-default-mail-gmail-refresh-token-mail_connection-conn_1",
        )
        grant_app_secret_use(
            app.state.secret_store,
            workspace_id="default",
            app_id="mail",
            logical_name="gmail-refresh-token",
            secret_ref=build_secret_ref(alias=secret.alias),
            actions=["app.backend"],
            target_patterns=[
                app_secret_target("backend", resource_type="mail_connection", resource_id="conn_1"),
                app_secret_target("cli/mail", resource_type="mail_connection", resource_id="conn_1"),
            ],
            resource_type="mail_connection",
            resource_id="conn_1",
            reason=APP_WRITE_GRANT_REASON,
        )

        status, payload, _ = self.invoke(app, path="/api/secret-grant-needs", cookie=cookie)

        self.assertEqual(status, 200)
        need = next(item for item in payload["items"] if item["logical_name"] == "gmail-refresh-token")
        self.assertEqual(
            need["scope"],
            {
                "type": "resource",
                "resource_type": "mail_connection",
                "resource_id": "conn_1",
                "label": "Mail Connection conn_1",
            },
        )
        self.assertEqual(
            need["recommended_grant"]["target_patterns"],
            [
                app_secret_target("backend", resource_type="mail_connection", resource_id="conn_1"),
                app_secret_target("cli/mail", resource_type="mail_connection", resource_id="conn_1"),
            ],
        )
        self.assertEqual(need["recommended_grant"]["resource_type"], "mail_connection")
        self.assertEqual(need["recommended_grant"]["resource_id"], "conn_1")
        self.assertEqual(need["value_state"], "managed_by_app_write")
        self.assertEqual(need["grant_state"], "active")
        self.assertEqual(need["user_action"], "none")
        self.assertEqual(need["credential_match"]["confidence"], "exact")
        self.assertTrue(need["app_managed"])

    def test_secret_grant_needs_model_mail_oauth_credentials_and_app_managed_refresh_token(self) -> None:
        app = self.make_app()
        cookie = self.login(app)
        self._enable_mail_app_with_resource_secret(app)

        status, payload, _ = self.invoke(app, path="/api/secret-grant-needs", cookie=cookie)

        self.assertEqual(status, 200)
        needs = {item["logical_name"]: item for item in payload["items"] if item["app_id"] == "mail"}
        self.assertEqual(set(needs), {"gmail-oauth-client-id", "gmail-oauth-client-secret", "gmail-refresh-token"})
        self.assertEqual(needs["gmail-oauth-client-id"]["scope"], {"type": "workspace", "label": "Workspace"})
        self.assertEqual(needs["gmail-oauth-client-secret"]["scope"], {"type": "workspace", "label": "Workspace"})
        self.assertFalse(needs["gmail-oauth-client-id"]["app_managed"])
        self.assertFalse(needs["gmail-oauth-client-secret"]["app_managed"])
        self.assertEqual(needs["gmail-refresh-token"]["scope"]["type"], "resource")
        self.assertEqual(needs["gmail-refresh-token"]["scope"]["resource_type"], "mail_connection")
        self.assertIsNone(needs["gmail-refresh-token"]["scope"]["resource_id"])
        self.assertEqual(needs["gmail-refresh-token"]["recommended_grant"]["resource_type"], "mail_connection")
        self.assertIsNone(needs["gmail-refresh-token"]["recommended_grant"]["resource_id"])
        self.assertTrue(needs["gmail-refresh-token"]["app_managed"])
        self.assertEqual(needs["gmail-refresh-token"]["user_action"], "complete_app_setup")
        self.assertNotIn("rt-secret-raw", json.dumps(payload))

    def test_secret_grant_needs_report_missing_grant_for_exact_alias_value(self) -> None:
        app = self.make_app()
        cookie = self.login(app)
        self.enable_workspace_app(app, secret_read=["api-token"], backend=True)
        create_platform_secret(app.state.secret_store, label="API Token", raw_value="api-secret", alias="api-token")

        status, payload, _ = self.invoke(app, path="/api/secret-grant-needs", cookie=cookie)

        self.assertEqual(status, 200)
        need = next(item for item in payload["items"] if item["logical_name"] == "api-token")
        self.assertEqual(need["value_state"], "available_ungranted")
        self.assertEqual(need["grant_state"], "missing")
        self.assertEqual(need["user_action"], "create_grant")
        self.assertEqual(need["credential_match"]["method"], "exact_alias")
        self.assertFalse(need["credential_match"]["ambiguous"])

    def test_secret_grant_needs_do_not_auto_link_label_candidates(self) -> None:
        app = self.make_app()
        cookie = self.login(app)
        self.enable_workspace_app(app, secret_read=["api-token"], backend=True)
        create_platform_secret(app.state.secret_store, label="API Token", raw_value="api-secret")

        status, payload, _ = self.invoke(app, path="/api/secret-grant-needs", cookie=cookie)

        self.assertEqual(status, 200)
        need = next(item for item in payload["items"] if item["logical_name"] == "api-token")
        self.assertEqual(need["value_state"], "candidate_needs_review")
        self.assertEqual(need["user_action"], "review_value_match")
        self.assertEqual(need["credential_match"]["method"], "exact_label")
        self.assertEqual(need["credential_match"]["confidence"], "review_required")
        self.assertTrue(need["credential_match"]["ambiguous"])
        self.assertFalse(need["credential_match"]["matched"])

    def test_secret_grant_needs_report_stale_revoked_and_orphaned_grant_issues(self) -> None:
        app = self.make_app()
        cookie = self.login(app)
        self.enable_workspace_app(
            app,
            secret_read=["disabled-token", "revoked-token", "orphan-token"],
            backend=True,
        )
        disabled_secret = create_platform_secret(
            app.state.secret_store,
            label="Disabled Token",
            raw_value="disabled-secret",
            alias="disabled-token",
        )
        revoked_secret = create_platform_secret(
            app.state.secret_store,
            label="Revoked Token",
            raw_value="revoked-secret",
            alias="revoked-token",
        )
        grant_app_secret_use(
            app.state.secret_store,
            workspace_id="default",
            app_id="browser",
            logical_name="disabled-token",
            secret_ref=build_secret_ref(alias=disabled_secret.alias),
            actions=["app.backend"],
            target_patterns=[app_secret_target("backend")],
        )
        revoked_grant = grant_app_secret_use(
            app.state.secret_store,
            workspace_id="default",
            app_id="browser",
            logical_name="revoked-token",
            secret_ref=build_secret_ref(alias=revoked_secret.alias),
            actions=["app.backend"],
            target_patterns=[app_secret_target("backend")],
        )
        grant_app_secret_use(
            app.state.secret_store,
            workspace_id="default",
            app_id="browser",
            logical_name="orphan-token",
            secret_ref=build_secret_ref(alias="missing-token"),
            actions=["app.backend"],
            target_patterns=[app_secret_target("backend")],
        )
        app.state.secret_store.save_secret(replace(disabled_secret, status="disabled"))
        revoke_app_secret_grant(app.state.secret_store, grant_id=revoked_grant.grant_id)

        status, payload, _ = self.invoke(app, path="/api/secret-grant-needs", cookie=cookie)

        self.assertEqual(status, 200)
        needs = {item["logical_name"]: item for item in payload["items"]}
        self.assertEqual(needs["disabled-token"]["value_state"], "disabled")
        self.assertEqual(needs["disabled-token"]["grant_state"], "stale_secret_disabled")
        self.assertEqual(needs["disabled-token"]["user_action"], "rotate_or_replace_value")
        self.assertEqual(needs["revoked-token"]["grant_state"], "revoked")
        self.assertEqual(needs["revoked-token"]["user_action"], "review_grant")
        self.assertEqual(needs["orphan-token"]["value_state"], "orphaned")
        self.assertEqual(needs["orphan-token"]["grant_state"], "orphaned")
        self.assertEqual(needs["orphan-token"]["user_action"], "add_value")

    def test_app_backend_grant_rejects_resource_scope_mismatches(self) -> None:
        app = self.make_app()
        cookie = self.login(app)
        self._enable_mail_app_with_resource_secret(app)
        _status, secret_payload, _ = self.invoke(
            app,
            path="/api/secrets",
            method="POST",
            cookie=cookie,
            body={"label": "Gmail", "raw_value": "gmail-secret"},
        )

        cases = [
            (
                {
                    "app_id": "mail",
                    "logical_name": "gmail-refresh-token",
                    "secret_id": secret_payload["secret"]["secret_id"],
                    "actions": ["app.backend"],
                    "target_patterns": ["maverick://app.backend/*"],
                },
                "requires resource_type and resource_id",
            ),
            (
                {
                    "app_id": "mail",
                    "logical_name": "gmail-refresh-token",
                    "secret_id": secret_payload["secret"]["secret_id"],
                    "actions": ["app.backend"],
                    "target_patterns": ["maverick://app.backend/*"],
                    "resource_type": "email_thread",
                    "resource_id": "thread_1",
                },
                "does not allow resource_type",
            ),
            (
                {
                    "app_id": "mail",
                    "logical_name": "gmail-oauth-client-id",
                    "secret_id": secret_payload["secret"]["secret_id"],
                    "actions": ["app.backend"],
                    "target_patterns": ["maverick://app.backend/*"],
                    "resource_type": "mail_connection",
                    "resource_id": "conn_1",
                },
                "workspace-scoped",
            ),
        ]

        for body, detail in cases:
            status, payload, _ = self.invoke(app, path="/api/secret-grants", method="POST", cookie=cookie, body=body)
            self.assertEqual(status, 400)
            self.assertEqual(payload["error"], "secret_error")
            self.assertIn(detail, payload["detail"])

    def test_app_backend_grant_accepts_declared_resource_scope_per_resource(self) -> None:
        app = self.make_app()
        cookie = self.login(app)
        self._enable_mail_app_with_resource_secret(app)
        _status, secret_payload, _ = self.invoke(
            app,
            path="/api/secrets",
            method="POST",
            cookie=cookie,
            body={"label": "Gmail", "raw_value": "gmail-secret"},
        )

        first_status, first_payload, _ = self.invoke(
            app,
            path="/api/secret-grants",
            method="POST",
            cookie=cookie,
            body={
                "app_id": "mail",
                "logical_name": "gmail-refresh-token",
                "secret_id": secret_payload["secret"]["secret_id"],
                "actions": ["app.backend"],
                "target_patterns": [
                    app_secret_target("backend", resource_type="mail_connection", resource_id="conn_1"),
                ],
                "resource_type": "mail_connection",
                "resource_id": "conn_1",
            },
        )
        second_status, second_payload, _ = self.invoke(
            app,
            path="/api/secret-grants",
            method="POST",
            cookie=cookie,
            body={
                "app_id": "mail",
                "logical_name": "gmail-refresh-token",
                "secret_id": secret_payload["secret"]["secret_id"],
                "actions": ["app.backend"],
                "target_patterns": ["maverick://app.backend/*"],
                "resource_type": "mail_connection",
                "resource_id": "conn_2",
            },
        )

        self.assertEqual(first_status, 201)
        self.assertEqual(second_status, 201)
        self.assertEqual(first_payload["grant"]["resource_type"], "mail_connection")
        self.assertEqual(first_payload["grant"]["resource_id"], "conn_1")
        self.assertEqual(
            first_payload["grant"]["target_patterns"],
            [app_secret_target("backend", resource_type="mail_connection", resource_id="conn_1")],
        )
        self.assertEqual(second_payload["grant"]["resource_id"], "conn_2")
        self.assertNotEqual(first_payload["grant"]["grant_id"], second_payload["grant"]["grant_id"])

    def test_app_backend_grant_rejects_target_pattern_for_different_resource_id(self) -> None:
        app = self.make_app()
        cookie = self.login(app)
        self._enable_mail_app_with_resource_secret(app)
        _status, secret_payload, _ = self.invoke(
            app,
            path="/api/secrets",
            method="POST",
            cookie=cookie,
            body={"label": "Gmail", "raw_value": "gmail-secret"},
        )

        status, payload, _ = self.invoke(
            app,
            path="/api/secret-grants",
            method="POST",
            cookie=cookie,
            body={
                "app_id": "mail",
                "logical_name": "gmail-refresh-token",
                "secret_id": secret_payload["secret"]["secret_id"],
                "actions": ["app.backend"],
                "target_patterns": [
                    app_secret_target("backend", resource_type="mail_connection", resource_id="conn_2"),
                ],
                "resource_type": "mail_connection",
                "resource_id": "conn_1",
            },
        )

        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "secret_error")
        self.assertIn("does not match grant resource scope", payload["detail"])

    def test_app_backend_grant_rejects_case_variant_duplicate_resource_scope(self) -> None:
        app = self.make_app()
        cookie = self.login(app)
        self._enable_mail_app_with_resource_secret(app)
        _status, secret_payload, _ = self.invoke(
            app,
            path="/api/secrets",
            method="POST",
            cookie=cookie,
            body={"label": "Gmail", "raw_value": "gmail-secret"},
        )

        first_status, _first_payload, _ = self.invoke(
            app,
            path="/api/secret-grants",
            method="POST",
            cookie=cookie,
            body={
                "app_id": "mail",
                "logical_name": "gmail-refresh-token",
                "secret_id": secret_payload["secret"]["secret_id"],
                "actions": ["app.backend"],
                "target_patterns": ["maverick://app.backend/*"],
                "resource_type": "mail_connection",
                "resource_id": "conn_1",
            },
        )
        duplicate_status, duplicate_payload, _ = self.invoke(
            app,
            path="/api/secret-grants",
            method="POST",
            cookie=cookie,
            body={
                "app_id": "mail",
                "logical_name": "gmail-refresh-token",
                "secret_id": secret_payload["secret"]["secret_id"],
                "actions": ["app.backend"],
                "target_patterns": ["maverick://app.backend/*"],
                "resource_type": "MAIL_CONNECTION",
                "resource_id": "Conn_1",
            },
        )
        list_status, list_payload, _ = self.invoke(app, path="/api/secret-grants", cookie=cookie)

        self.assertEqual(first_status, 201)
        self.assertEqual(duplicate_status, 400)
        self.assertEqual(duplicate_payload["error"], "secret_error")
        self.assertIn("overlapping targets", duplicate_payload["detail"])
        self.assertEqual(list_status, 200)
        self.assertEqual(len(list_payload["items"]), 1)
        self.assertEqual(list_payload["items"][0]["resource_type"], "mail_connection")
        self.assertEqual(list_payload["items"][0]["resource_id"], "conn_1")

    def test_grant_create_rejects_query_string_target_patterns(self) -> None:
        app = self.make_app()
        cookie = self.login(app)
        self.enable_workspace_app(app)
        _status, secret_payload, _ = self.invoke(
            app,
            path="/api/secrets",
            method="POST",
            cookie=cookie,
            body={"label": "Browser Login", "raw_value": "browser-secret"},
        )

        for logical_name, target_patterns in (("login", ["https://example.com/login?token=*"]), ("empty-target", [])):
            status, payload, _ = self.invoke(
                app,
                path="/api/secret-grants",
                method="POST",
                cookie=cookie,
                body={
                    "app_id": "browser",
                    "logical_name": logical_name,
                    "secret_id": secret_payload["secret"]["secret_id"],
                    "actions": ["browser.autofill"],
                    "target_patterns": target_patterns,
                },
            )
            self.assertEqual(status, 400)
            self.assertEqual(payload["error"], "secret_error")

    def test_grant_record_management_is_workspace_scoped(self) -> None:
        app = self.make_app()
        cookie = self.login(app)
        secret = create_platform_secret(app.state.secret_store, label="Other Workspace", raw_value="other-secret")
        grant = grant_app_secret_use(
            app.state.secret_store,
            workspace_id="acme",
            app_id="browser",
            logical_name="login",
            secret_ref=build_secret_ref(secret_id=secret.secret_id),
            actions=["browser.autofill"],
            target_patterns=["https://example.com/*"],
        )

        status, payload, _ = self.invoke(app, path=f"/api/secret-grants/{grant.grant_id}", cookie=cookie)

        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "secret_error")

    def test_secret_api_requires_admin(self) -> None:
        app = self.make_app()
        member = create_user(app.state.identity_store, username="member", password="member-pass", platform_role="member")
        ensure_workspace_membership(
            app.state.workspace_store,
            membership_id="default:member",
            workspace_id="default",
            user_id=member.user_id,
            role="member",
        )
        cookie = self.login(app, username="member", password="member-pass")

        status, payload, _ = self.invoke(app, path="/api/secrets", cookie=cookie)
        targets_status, targets_payload, _ = self.invoke(app, path="/api/secret-grant-targets", cookie=cookie)
        needs_status, needs_payload, _ = self.invoke(app, path="/api/secret-grant-needs", cookie=cookie)

        self.assertEqual(status, 403)
        self.assertEqual(payload["error"], "admin_required")
        self.assertEqual(targets_status, 403)
        self.assertEqual(targets_payload["error"], "admin_required")
        self.assertEqual(needs_status, 403)
        self.assertEqual(needs_payload["error"], "admin_required")

    def _enable_mail_app_with_resource_secret(self, app) -> None:
        self.enable_workspace_app(
            app,
            app_id="mail",
            secret_read=["gmail-oauth-client-id", "gmail-oauth-client-secret", "gmail-refresh-token"],
            backend=True,
            cli_commands=["mail"],
        )
        app_root = app.state.repository_root / "apps" / "mail"
        contract_path = app_root / "app_contract.json"
        contract_payload = json.loads(contract_path.read_text(encoding="utf-8"))
        contract_payload["permissions"]["secrets"]["write"] = ["gmail-refresh-token"]
        contract_path.write_text(json.dumps(contract_payload, indent=2), encoding="utf-8")
        (app_root / "cli").mkdir(parents=True, exist_ok=True)
        (app_root / "cli" / "command_schemas.json").write_text(
            json.dumps(
                {
                    "commands": {
                        "mail": {
                            "secret_selectors": [
                                {"required_secrets": ["gmail-oauth-client-id"]},
                                {"required_secrets": ["gmail-oauth-client-id", "gmail-oauth-client-secret"]},
                                {
                                    "required_secrets": ["gmail-refresh-token"],
                                    "resource_type": "mail_connection",
                                    "resource_lookup": {"kind": "mail_connection_from_arguments"},
                                },
                            ]
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
