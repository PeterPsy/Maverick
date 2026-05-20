"""Tests for the core secret HTTP API used by Vault."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json

from core.identity.service import create_user
from core.secrets.service import build_secret_ref, create_platform_secret, grant_app_secret_use
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
        self.enable_workspace_app(app, secret_read=["api-token"])
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
        self.enable_workspace_app(app, secret_read=["declared-token"])
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

    def test_expired_grants_are_reported_and_do_not_block_replacement(self) -> None:
        app = self.make_app()
        cookie = self.login(app)
        self.enable_workspace_app(app, secret_read=["api-token"])
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
        self.enable_workspace_app(app, secret_read=["api-token", "webhook-token"])

        registry_status, registry_payload, _ = self.invoke(app, path="/api/apps", cookie=cookie)
        targets_status, targets_payload, _ = self.invoke(app, path="/api/secret-grant-targets", cookie=cookie)

        self.assertEqual(registry_status, 200)
        self.assertEqual(targets_status, 200)
        self.assertNotIn("permissions", json.dumps(registry_payload))
        target = next(item for item in targets_payload["items"] if item["app_id"] == "browser")
        self.assertEqual(target["logical_names"], ["api-token", "webhook-token"])

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

        self.assertEqual(status, 403)
        self.assertEqual(payload["error"], "admin_required")
        self.assertEqual(targets_status, 403)
        self.assertEqual(targets_payload["error"], "admin_required")
