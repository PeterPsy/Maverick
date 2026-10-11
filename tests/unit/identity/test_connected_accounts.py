"""Google consent must preserve identity, ownership and capability boundaries."""

import base64
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from core.api.connected_accounts_api import handle_connected_accounts_api, provider_status
from core.api.session_api import RequestSession
from core.api.sidecar_entrypoint_invocation import run_json_entrypoint_with_sidecars
from core.apps.contracts import parse_app_contract_file
from core.apps.registration import build_workspace_app_binding_record
from core.apps.service import register_app_source_from_contract
from core.apps.store import AppCollections, AppDocumentStore
from core.cli.models import CliInvocationContext
from core.cli.registry_builder import build_core_cli_registry
from core.cli.runner import CliRunner
from core.mcp.models import McpInvocationContext
from core.mcp.registry_builder import build_core_mcp_registry
from core.mcp.runner import McpRunner
from core.app_sdk.connected_accounts import account_urlopen
from core.connected_accounts.app_context import account_context, filter_secret_requests
from core.connected_accounts.broker import AccountBroker
from core.connected_accounts.google import AccountError, SERVICES, allowed_api_request
from core.connected_accounts.google_identity import verify_identity
from core.connected_accounts.service import complete_flow, disconnect_account, select_account, start_flow
from core.connected_accounts.store import AccountCollections, AccountDocumentStore
from core.identity.service import build_auth_session, build_user_record
from core.identity.store import IdentityCollections, IdentityDocumentStore
from core.secrets.app_delivery import AppSecretRequest
from core.secrets.service import create_platform_secret
from core.secrets.store import SecretCollections, SecretDocumentStore
from core.shared.in_memory_collection import InMemoryCollection
from core.workspaces.service import build_workspace_record, ensure_workspace_membership
from core.workspaces.store import WorkspaceCollections, WorkspaceDocumentStore

ROOT = Path(__file__).resolve().parents[3]


class ConnectedAccountsTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(UTC)
        self.accounts = AccountDocumentStore(AccountCollections(*(InMemoryCollection() for _ in range(3))))
        self.identity = IdentityDocumentStore(IdentityCollections(*(InMemoryCollection() for _ in range(3))), account_store=self.accounts)
        self.workspace = WorkspaceDocumentStore(WorkspaceCollections(*(InMemoryCollection() for _ in range(5))))
        self.workspace.save_workspace(build_workspace_record(workspace_id="default", name="Default", slug="default", now=self.now))
        self.user = self.identity.save_user(build_user_record(user_id="user:alice", username="alice", email="alice@example.com", now=self.now))
        ensure_workspace_membership(self.workspace, membership_id="alice-default", workspace_id="default", user_id=self.user.user_id, role="member", now=self.now)
        session = build_auth_session(session_id="session-alice", user_id=self.user.user_id, expires_at=self.now + timedelta(days=1), now=self.now)
        self.context = RequestSession(self.user, session, "default")
        self.secrets = SecretDocumentStore(SecretCollections(*(InMemoryCollection() for _ in range(4))), key_loader=lambda: b"k" * 32)
        create_platform_secret(self.secrets, label="Client id", secret_id="client-id", alias="google-oauth-client-id", raw_value="test-client")
        create_platform_secret(self.secrets, label="Client secret", secret_id="client-secret", alias="google-oauth-client-secret", raw_value="private-client-secret")
        self.state = SimpleNamespace(account_store=self.accounts, identity_store=self.identity, workspace_store=self.workspace,
                                     secret_store=self.secrets, repository_root=ROOT)
        self.environment = patch.dict("os.environ", {"MAVERICK_GOOGLE_REDIRECT_URI": "https://maverick.example/api/auth/google/callback",
            "MAVERICK_GOOGLE_ALLOW_REGISTRATION": "1", "MAVERICK_GOOGLE_CLIENT_ID_REF": "platform:secret-alias/google-oauth-client-id",
            "MAVERICK_GOOGLE_CLIENT_SECRET_REF": "platform:secret-alias/google-oauth-client-secret"})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def flow(self, services=None, mode="connect", context=None):
        result, browser = start_flow(self.state, mode=mode, services=services or [],
                                     context=self.context if mode == "connect" and context is None else context, now=self.now)
        query = parse_qs(urlsplit(result["authorization_url"]).query)
        return query, browser

    def complete(self, query, browser, *, context=None, subject="subject-alice", email="alice@example.com", scopes=None, refresh="private-refresh"):
        tokens = {"id_token": "signed-token", "scope": " ".join(scopes if scopes is not None else SERVICES["calendar"]["scopes"]), "refresh_token": refresh}
        return complete_flow(self.state, raw_state=query["state"][0], browser=browser, code="auth-code",
            context=context or self.context, now=self.now, exchange=lambda *args, **kwargs: tokens,
            identity_verifier=lambda *args, **kwargs: {"sub": subject, "email": email, "name": "Alice"})

    def test_authorization_has_pkce_and_persists_no_browser_or_state_secret(self):
        query, browser = self.flow(["calendar", "gmail"])
        self.assertEqual(query["code_challenge"][0], base64.urlsafe_b64encode(sha256(browser.encode()).digest()).decode().rstrip("="))
        self.assertEqual(query["access_type"], ["offline"])
        self.assertEqual(query["include_granted_scopes"], ["true"])
        metadata = repr(self.accounts.collections.flows.find({}))
        self.assertNotIn(browser, metadata)
        self.assertNotIn(query["state"][0], metadata)

    def test_wrong_browser_does_not_consume_flow_but_replay_does(self):
        query, browser = self.flow(["calendar"])
        with self.assertRaisesRegex(AccountError, "google_flow_invalid"):
            self.complete(query, "wrong-browser")
        self.complete(query, browser)
        with self.assertRaisesRegex(AccountError, "google_flow_invalid"):
            self.complete(query, browser)

    def test_expired_flow_and_changed_login_are_rejected(self):
        query, browser = self.flow(["calendar"])
        with self.assertRaisesRegex(AccountError, "google_flow_invalid"):
            complete_flow(self.state, raw_state=query["state"][0], browser=browser, code="code", context=self.context, now=self.now + timedelta(minutes=11))
        query, browser = self.flow(["calendar"])
        changed = replace(self.context, session=replace(self.context.session, session_id="another-session"))
        with self.assertRaisesRegex(AccountError, "google_flow_session_changed"):
            self.complete(query, browser, context=changed)

    def test_linked_identity_preserves_user_and_stores_only_actual_grants(self):
        query, browser = self.flow(["calendar", "gmail"])
        user, account, mode, selection = self.complete(query, browser)
        self.assertEqual(user.user_id, self.user.user_id)
        self.assertEqual(mode, "connect")
        self.assertEqual(account.scopes, sorted(SERVICES["calendar"]["scopes"]))
        self.assertEqual(selection.workspace_id, "default")
        self.assertNotIn("private-refresh", repr(self.accounts.collections.accounts.find({})))
        self.assertNotIn("private-refresh", repr(self.secrets.collections.values.find({})))
        login_query, login_browser = self.flow(mode="login")
        again, _, _, _ = self.complete(login_query, login_browser, refresh="")
        self.assertEqual(again, self.user)

    def test_google_cannot_automatically_take_over_matching_email(self):
        query, browser = self.flow(mode="login")
        with self.assertRaisesRegex(AccountError, "google_account_link_required"):
            self.complete(query, browser)
        self.assertEqual(self.accounts.list_accounts(self.user.user_id), [])

    def test_new_registration_has_no_workspace_or_admin_privilege(self):
        query, browser = self.flow(mode="login")
        user, _, _, selection = self.complete(query, browser, subject="new-subject", email="new@example.com", scopes=[], refresh="")
        self.assertEqual(user.platform_role, "member")
        self.assertEqual(self.workspace.list_memberships_for_user(user.user_id), [])
        self.assertIsNone(selection)

    def test_another_user_cannot_link_or_select_owned_google_account(self):
        query, browser = self.flow(["calendar"])
        _, account, _, _ = self.complete(query, browser)
        bob = self.identity.save_user(build_user_record(user_id="user:bob", username="bob", now=self.now))
        other = replace(self.context, user=bob)
        query, browser = self.flow(["calendar"], context=other)
        with self.assertRaisesRegex(AccountError, "google_account_already_linked"):
            self.complete(query, browser, context=other)
        with self.assertRaisesRegex(AccountError, "account_not_found"):
            select_account(self.state, user_id=bob.user_id, workspace_id="default", account_id=account.account_id)

    def test_provider_status_does_not_return_credential_values(self):
        status = provider_status(self.state)
        self.assertTrue(status["configured"])
        self.assertNotIn("test-client", json.dumps(status))
        self.assertNotIn("private-client-secret", json.dumps(status))

    def test_login_services_follow_enabled_contracts_and_hide_installation_inventory(self):
        apps = AppDocumentStore(AppCollections(*(InMemoryCollection() for _ in range(5))))
        self.state.app_store = apps
        archived = replace(build_workspace_record(workspace_id="private-archive", name="Private archive", slug="archive", now=self.now), status="archived")
        self.workspace.save_workspace(archived)
        bindings = []
        for workspace_id, app, status in [("default", "calendar", "enabled"), ("default", "storage", "enabled"),
                                           ("default", "mail", "disabled"), (archived.workspace_id, "mail", "enabled")]:
            source = register_app_source_from_contract(apps, source_kind="platform", source_path=str(ROOT / "apps" / app))
            binding = build_workspace_app_binding_record(workspace_id=workspace_id, app_id=app,
                source_record_id=source.source_id, source_kind="platform", status=status, active_version=source.version, data_root="/unused")
            apps.save_workspace_app_binding(binding)
            bindings.append(binding)
        status = provider_status(self.state)
        self.assertEqual(status["login_services"], ["calendar", "drive"])
        self.assertNotIn(archived.workspace_id, json.dumps(status))
        apps.save_workspace_app_binding(replace(bindings[2], status="enabled"))
        self.assertEqual(provider_status(self.state)["login_services"], ["calendar", "gmail", "drive"])
        apps.save_workspace_app_binding(replace(bindings[0], status="disabled"))
        self.assertEqual(provider_status(self.state)["login_services"], ["gmail", "drive"])

    def test_start_rejects_cross_origin_and_isolated_frame_requests(self):
        for origin, frame in [("https://evil.example", False), ("https://maverick.example", True)]:
            headers = []
            environ = {"PATH_INFO": "/api/auth/google/start", "REQUEST_METHOD": "POST", "HTTP_ORIGIN": origin,
                       "maverick.app_frame_proxy": frame, "wsgi.url_scheme": "https", "HTTP_HOST": "maverick.example", "wsgi.input": BytesIO(), "CONTENT_LENGTH": "0"}
            with patch("core.api.connected_accounts_api.resolve_request_session", return_value=self.context):
                result = handle_connected_accounts_api(self.state, environ, lambda status, _: headers.append(status))
            self.assertEqual(headers, ["403 Forbidden"])
            self.assertEqual(json.loads(b"".join(result))["error"], "origin_not_allowed")

    def personal_context(self, root, app="calendar"):
        return account_context(identity_store=self.identity, workspace_store=self.workspace,
            permissions=parse_app_contract_file(ROOT / "apps" / app).contract.permissions,
            user_id=self.user.user_id, workspace_id="default", app_id=app, data_root=root)

    def test_private_app_root_and_secret_replacement_preserve_manual_state(self):
        query, browser = self.flow(["calendar"])
        self.complete(query, browser)
        with tempfile.TemporaryDirectory() as root:
            Path(root, "manual-state.txt").write_text("Existing manual data")
            context = self.personal_context(root)
            self.assertIn("connected-accounts", context["data_root"])
            self.assertEqual(Path(root, "manual-state.txt").read_text(), "Existing manual data")
            requests = filter_secret_requests([AppSecretRequest(["google-calendar-refresh-token"]), AppSecretRequest(["unrelated-secret"])], context)
            self.assertEqual([item.logical_names for item in requests], [["unrelated-secret"]])
            selection = self.accounts.get_selection(self.user.user_id, "default")
            self.accounts.save_selection(replace(selection, disabled_apps=["calendar"]))
            disabled = self.personal_context(root)
            self.assertEqual(disabled["accounts"], [])
            self.assertEqual(disabled["data_root"], context["data_root"])

    def test_broker_forwards_scoped_api_without_exposing_google_token(self):
        query, browser = self.flow(["calendar"])
        _, account, _, _ = self.complete(query, browser)
        forwarded = []
        def sender(request):
            forwarded.append(request)
            return 200, {"Content-Type": "application/json"}, b'{"items": []}'
        with tempfile.TemporaryDirectory() as root:
            context = self.personal_context(root)
            broker = AccountBroker(context=context, identity_store=self.identity, workspace_store=self.workspace,
                secret_store=self.secrets, app_store=None, permissions=parse_app_contract_file(ROOT / "apps/calendar").contract.permissions,
                user_id=self.user.user_id, workspace_id="default", app_id="calendar", data_root=root, sender=sender)
            handle = broker.start()
            try:
                self.assertNotIn("private-refresh", handle)
                with patch("core.connected_accounts.broker.google.json_request", return_value={"access_token": "private-access", "expires_in": 3600}):
                    with account_urlopen(Request("https://www.googleapis.com/calendar/v3/users/me/calendarList", headers={"Authorization": "Bearer " + handle})) as response:
                        self.assertEqual(json.loads(response.read()), {"items": []})
                self.assertEqual(forwarded[0].get_header("Authorization"), "Bearer private-access")
                with self.assertRaises(Exception):
                    account_urlopen(Request("https://gmail.googleapis.com/gmail/v1/users/me/messages", headers={"Authorization": "Bearer " + handle}))
                self.accounts.save_account(replace(account, status="disconnected"))
                with self.assertRaises(Exception):
                    account_urlopen(Request("https://www.googleapis.com/calendar/v3/users/me/calendarList", headers={"Authorization": "Bearer " + handle}))
                self.assertEqual(len(forwarded), 1)
            finally:
                socket_root = broker.root
                broker.close()
            self.assertFalse(socket_root.exists())

    def test_disconnect_with_provider_outage_withdraws_local_authority(self):
        query, browser = self.flow(["calendar"])
        _, account, _, _ = self.complete(query, browser)
        with patch("core.connected_accounts.service.google.provider_request", side_effect=AccountError("google_unavailable")):
            result = disconnect_account(self.state, user_id=self.user.user_id, account_id=account.account_id)
        self.assertFalse(result["revoked_at_google"])
        self.assertEqual(self.accounts.get_account(account.account_id).status, "disconnected")
        self.assertEqual(self.secrets.get_secret(account.secret_ref.rsplit("/", 1)[-1]).status, "revoked")

    def test_provider_policy_rejects_host_method_path_and_redirect_escalation(self):
        for url in ["http://www.googleapis.com/calendar/v3/users/me/calendarList", "https://www.googleapis.com.evil.example/calendar/v3/users/me/calendarList",
                    "https://www.googleapis.com/calendar/v3/../gmail/v1/users/me/messages", "https://www.googleapis.com/calendar/v3/calendars/me/acl",
                    "https://user:pass@www.googleapis.com/calendar/v3/users/me/calendarList"]:
            self.assertFalse(allowed_api_request(["calendar"], "GET", url), url)
        self.assertFalse(allowed_api_request(["calendar"], "DELETE", "https://www.googleapis.com/calendar/v3/users/me/calendarList"))
        self.assertTrue(allowed_api_request(["calendar"], "PATCH", "https://www.googleapis.com/calendar/v3/calendars/me/events/evt"))
        attachment = "https://gmail.googleapis.com/gmail/v1/users/me/messages/msg/attachments/attachment"
        self.assertTrue(allowed_api_request(["gmail"], "GET", attachment))
        self.assertFalse(allowed_api_request(["gmail"], "DELETE", attachment))
        self.assertFalse(allowed_api_request(["calendar"], "GET", attachment))

    def test_real_app_entrypoints_project_shared_account_without_oauth(self):
        query, browser = self.flow(["calendar", "gmail", "drive"])
        scopes = [scope for service in SERVICES.values() for scope in service["scopes"]]
        _, account, _, _ = self.complete(query, browser, scopes=scopes)
        for app, action in [("calendar", "calendar_connections.list"), ("mail", "connections.list"), ("storage", "drive_connections.list")]:
            with self.subTest(app=app), tempfile.TemporaryDirectory() as root:
                source = ROOT / "apps" / app
                parsed = parse_app_contract_file(source)
                binding = SimpleNamespace(workspace_id="default", app_id=app, data_root=root)
                result = run_json_entrypoint_with_sidecars(source / parsed.contract.entrypoints.backend,
                    payload={"surface": "backend", "workspace_id": "default", "app_id": app, "data_root": root,
                        "user_id": self.user.user_id, "body": {"action": action}, "app_secrets": {},
                        "uploaded_storage_root": str(Path(root) / "uploaded"), "generated_storage_root": str(Path(root) / "generated")},
                    cwd=source, binding=binding, parsed=parsed, surface="backend", start_path=ROOT,
                    actor_user_id=self.user.user_id, runtime_session_id=None,
                    identity_store=self.identity, workspace_store=self.workspace, secret_store=self.secrets)
                self.assertEqual(result["status_code"], 200, result)
                public = result["json"]
                self.assertIn("platform_" + account.account_id, json.dumps(public))
                self.assertNotIn("private-refresh", json.dumps(public))
                self.assertNotIn("maverick-account:", json.dumps(public))
                prefix = {"calendar": "calendar_connections", "mail": "connections", "storage": "drive_connections"}[app]
                for action in [prefix + ".start_oauth", prefix + ".disconnect"]:
                    denied = run_json_entrypoint_with_sidecars(source / parsed.contract.entrypoints.backend,
                        payload={"surface": "backend", "workspace_id": "default", "app_id": app, "data_root": root,
                            "user_id": self.user.user_id, "body": {"action": action, "provider": "google" if app == "calendar" else "gmail" if app == "mail" else "google_drive",
                                "connection_id": "platform_" + account.account_id}, "app_secrets": {},
                            "uploaded_storage_root": str(Path(root) / "uploaded"), "generated_storage_root": str(Path(root) / "generated")},
                        cwd=source, binding=binding, parsed=parsed, surface="backend", start_path=ROOT,
                        actor_user_id=self.user.user_id, runtime_session_id=None,
                        identity_store=self.identity, workspace_store=self.workspace, secret_store=self.secrets)
                    self.assertGreaterEqual(denied["status_code"], 400, denied)
                    self.assertIn("Maverick Connected accounts", json.dumps(denied["json"]))

    def test_callback_creates_platform_cookie_and_pending_registration_does_not(self):
        query, browser = self.flow(["calendar"])
        user, account, _, selection = self.complete(query, browser)
        for membership in [selection, None]:
            login_query, login_browser = self.flow(mode="login")
            captured = []
            environ = {"PATH_INFO": "/api/auth/google/callback", "REQUEST_METHOD": "GET", "wsgi.url_scheme": "https",
                "HTTP_COOKIE": "maverick_google_flow=" + login_browser,
                "QUERY_STRING": "code=code&state=" + login_query["state"][0]}
            with patch("core.api.connected_accounts_api.resolve_request_session", return_value=None), patch(
                    "core.api.connected_accounts_api.complete_claimed_flow", return_value=(user, account, "login", membership)):
                handle_connected_accounts_api(self.state, environ, lambda status, headers: captured.extend(headers))
            cookies = [value for name, value in captured if name == "Set-Cookie"]
            self.assertTrue(any("maverick_google_flow=;" in cookie for cookie in cookies))
            self.assertEqual(any(cookie.startswith("maverick_session=") for cookie in cookies), membership is not None)
            self.assertNotIn("private-refresh", repr(captured))

    def test_real_cli_and_mcp_registries_reuse_the_personal_connection(self):
        query, browser = self.flow(["calendar", "gmail", "drive"])
        self.complete(query, browser, scopes=[scope for service in SERVICES.values() for scope in service["scopes"]])
        for app, action, tool in [("calendar", "calendar_connections.list", "calendar_connections.list"),
                                  ("mail", "connections.list", "mail_list_threads"),
                                  ("storage", "drive_connections.list", "storage_drive_connections_list")]:
            with self.subTest(app=app), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                apps = AppDocumentStore(AppCollections(*(InMemoryCollection() for _ in range(5))))
                source = register_app_source_from_contract(apps, source_kind="platform", source_path=str(ROOT / "apps" / app))
                apps.save_workspace_app_binding(build_workspace_app_binding_record(workspace_id="default", app_id=app,
                    source_record_id=source.source_id, source_kind="platform", status="enabled", active_version=source.version, data_root=str(root / "data")))
                paths = SimpleNamespace(root=root, uploaded_storage=root / "uploaded", generated_storage=root / "generated")
                paths.uploaded_storage.mkdir(); paths.generated_storage.mkdir()
                cli_context = CliInvocationContext("operator", "default", None, "full-access", user_id=self.user.user_id)
                mcp_context = McpInvocationContext("operator", "default", None, "full-access", user_id=self.user.user_id)
                stores = dict(app_store=apps, identity_store=self.identity, workspace_store=self.workspace,
                              secret_store=self.secrets, workspace_id="default", start_path=ROOT)
                with patch("core.cli.app_commands.workspace_paths", return_value=paths), patch("core.mcp.app_tools.workspace_paths", return_value=paths):
                    cli = CliRunner(build_core_cli_registry(**stores, context=cli_context))
                    mcp = McpRunner(build_core_mcp_registry(**stores, context=mcp_context))
                listed = cli.run_command(command_id=f"app.{app}.{app}", arguments={"action": action}, context=cli_context)
                self.assertEqual(listed["status_code"], 200, listed)
                self.assertIn("platform_google_", json.dumps(listed))
                result = mcp.call_tool(tool_name=f"app.{app}.{tool}", arguments={}, context=mcp_context)
                self.assertEqual(result.get("status_code", 200), 200, result)
                self.assertNotIn("private-refresh", json.dumps(result))
                self.assertNotIn("maverick-account:", json.dumps(result))

    def test_personal_context_does_not_cross_actor_or_membership_boundaries(self):
        query, browser = self.flow(["calendar"])
        self.complete(query, browser)
        with tempfile.TemporaryDirectory() as root:
            original = self.personal_context(root)
            self.assertIsNotNone(original)
            bob = self.identity.save_user(build_user_record(user_id="user:bob", username="bob", now=self.now))
            ensure_workspace_membership(self.workspace, membership_id="bob-default", workspace_id="default", user_id=bob.user_id, role="member", now=self.now)
            other = account_context(identity_store=self.identity, workspace_store=self.workspace,
                permissions=parse_app_contract_file(ROOT / "apps/calendar").contract.permissions,
                user_id=bob.user_id, workspace_id="default", app_id="calendar", data_root=root)
            self.assertIsNone(other)
            self.workspace.delete_memberships_for_user(self.user.user_id)
            self.assertIsNone(self.personal_context(root))


class GoogleIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        numbers = cls.key.public_key().public_numbers()
        encode_int = lambda value: base64.urlsafe_b64encode(value.to_bytes((value.bit_length()+7)//8, "big")).decode().rstrip("=")
        cls.keys = {"key": {"e": encode_int(numbers.e), "n": encode_int(numbers.n)}}

    def token(self, changes=None):
        claims = {"iss": "https://accounts.google.com", "aud": "client", "sub": "google-sub", "email": "user@example.com",
                  "email_verified": True, "nonce": "browser-nonce", "exp": 2000, "iat": 900, **(changes or {})}
        encode = lambda value: base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
        signed = encode({"alg": "RS256", "kid": "key"}) + "." + encode(claims)
        signature = self.key.sign(signed.encode(), padding.PKCS1v15(), hashes.SHA256())
        return signed + "." + base64.urlsafe_b64encode(signature).decode().rstrip("=")

    def test_signed_identity_checks_audience_nonce_expiry_verified_email(self):
        self.assertEqual(verify_identity(self.token(), client_id="client", nonce="browser-nonce", now=1000, keys=self.keys)["sub"], "google-sub")
        for change in [{"aud": "other"}, {"nonce": "wrong"}, {"exp": 999}, {"email_verified": False}, {"iss": "https://evil.example"}]:
            with self.assertRaisesRegex(AccountError, "google_identity_invalid"):
                verify_identity(self.token(change), client_id="client", nonce="browser-nonce", now=1000, keys=self.keys)

    def test_tampered_signature_is_rejected(self):
        token = self.token()
        parts = token.split(".")
        parts[2] = ("A" if parts[2][0] != "A" else "B") + parts[2][1:]
        with self.assertRaisesRegex(AccountError, "google_identity_invalid"):
            verify_identity(".".join(parts), client_id="client", nonce="browser-nonce", now=1000, keys=self.keys)
