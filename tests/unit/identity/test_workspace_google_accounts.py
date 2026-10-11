"""Multiple personal accounts remain explicitly scoped to each workspace."""

from dataclasses import asdict, replace
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request

from tests.unit.identity import test_connected_accounts as fixtures
from core.api.connected_accounts_api import handle_connected_accounts_api
from core.api.sidecar_entrypoint_invocation import run_json_entrypoint_with_sidecars
from core.apps.contracts import parse_app_contract_file
from core.app_sdk.connected_accounts import account_for_capability, account_urlopen, platform_access_handle
from core.connected_accounts.app_context import account_context
from core.connected_accounts.broker import AccountInvocation
from core.connected_accounts.google import AccountError, SERVICES
from core.connected_accounts.service import select_account, set_workspace_account_access
from core.workspaces.service import build_workspace_record, ensure_workspace_membership
from core.shared.json_file_collection import JsonFileCollection
from core.connected_accounts.store import AccountCollections, AccountDocumentStore

ROOT = fixtures.ROOT


class WorkspaceGoogleAccountsTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.ConnectedAccountsTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        scopes = [scope for service in SERVICES.values() for scope in service["scopes"]]
        self.accounts = [self.f.complete(*self.f.flow(), subject=f"subject-{i}", email=f"account-{i}@example.com",
                                       scopes=scopes, refresh=f"private-refresh-{i}")[1] for i in range(2)]
        self.f.workspace.save_workspace(build_workspace_record(workspace_id="second", name="Second", slug="second", now=self.f.now))
        ensure_workspace_membership(self.f.workspace, membership_id="alice-second", workspace_id="second",
                                    user_id=self.f.user.user_id, role="member", now=self.f.now)

    def context(self, root, workspace="default", account_id=None):
        return account_context(identity_store=self.f.identity, workspace_store=self.f.workspace,
            permissions=parse_app_contract_file(ROOT / "apps/calendar").contract.permissions,
            user_id=self.f.user.user_id, workspace_id=workspace, app_id="calendar", data_root=root, account_id=account_id)

    def enable(self, account, workspace="default", enabled=True):
        return set_workspace_account_access(self.f.state, user_id=self.f.user.user_id, workspace_id=workspace,
                                            account_id=account.account_id, enabled=enabled)

    def test_each_workspace_has_an_independent_account_set_and_default(self):
        with tempfile.TemporaryDirectory() as root:
            first = self.context(Path(root) / "default")
            self.assertEqual(len(first["accounts"]), 2)
            self.assertIsNone(self.context(Path(root) / "second", "second"))
            self.enable(self.accounts[0], "second")
            second = self.context(Path(root) / "second", "second")
            self.assertEqual([item["account"].account_id for item in second["accounts"]], [self.accounts[0].account_id])
            self.assertNotEqual(first["data_root"], second["data_root"])
            select_account(self.f.state, user_id=self.f.user.user_id, workspace_id="default", account_id=self.accounts[0].account_id)
            self.assertEqual(first["data_root"], self.context(Path(root) / "default")["data_root"])
            self.enable(self.accounts[0], enabled=False)
            self.assertEqual(len(self.context(Path(root) / "default")["accounts"]), 1)
            self.assertEqual(len(self.context(Path(root) / "second", "second")["accounts"]), 1)
            self.enable(self.accounts[1], enabled=False)
            empty = self.context(Path(root) / "default")
            self.assertEqual(empty["accounts"], [])
            self.assertEqual(empty["data_root"], first["data_root"])

    def test_existing_single_account_selection_enables_only_its_original_account(self):
        selection = self.f.accounts.get_selection(self.f.user.user_id, "default")
        old = asdict(selection)
        old.pop("account_ids")
        self.f.accounts.collections.selections.delete_one({"selection_id": selection.selection_id})
        self.f.accounts.collections.selections.update_one({"selection_id": selection.selection_id}, {"$set": old}, upsert=True)
        migrated = self.f.accounts.get_selection(self.f.user.user_id, "default")
        self.assertEqual(migrated.account_ids, [selection.account_id])

    def test_file_adapter_upgrades_and_persists_workspace_account_sets(self):
        with tempfile.TemporaryDirectory() as scratch:
            collections = AccountCollections(*(JsonFileCollection(Path(scratch) / (name + ".json"))
                                               for name in ("accounts", "selections", "flows")))
            store = AccountDocumentStore(collections)
            old = asdict(self.f.accounts.get_selection(self.f.user.user_id, "default"))
            old.pop("account_ids")
            collections.selections.update_one({"selection_id": old["selection_id"]}, {"$set": old}, upsert=True)
            updated = store.update_selection(self.f.user.user_id, "default",
                lambda selection: replace(selection, account_ids=[item.account_id for item in self.accounts]))
            self.assertEqual(AccountDocumentStore(collections).get_selection(self.f.user.user_id, "default"), updated)

    def test_membership_ownership_and_connection_status_gate_workspace_enablement(self):
        with self.assertRaisesRegex(AccountError, "workspace_access_required"):
            self.enable(self.accounts[0], "missing")
        self.f.accounts.save_account(replace(self.accounts[0], user_id="other-user"))
        with self.assertRaisesRegex(AccountError, "account_not_found"):
            self.enable(self.accounts[0])
        self.f.accounts.save_account(replace(self.accounts[0], status="disconnected"))
        with self.assertRaisesRegex(AccountError, "google_reconnect_required"):
            self.enable(self.accounts[0])
        self.enable(self.accounts[0], enabled=False)
        with self.assertRaisesRegex(AccountError, "invalid_account_access"):
            set_workspace_account_access(self.f.state, user_id=self.f.user.user_id, workspace_id="default",
                                         account_id=self.accounts[1].account_id, enabled="true")

    def test_workspace_access_route_requires_same_origin_and_returns_the_account_set(self):
        body = json.dumps({"workspace_id": "default", "account_id": self.accounts[0].account_id, "enabled": False}).encode()
        for origin, expected in [("https://evil.example", "403"), ("https://maverick.example", "200")]:
            captured = []
            environ = {"PATH_INFO": "/api/connected-accounts/workspace-access", "REQUEST_METHOD": "POST",
                "HTTP_ORIGIN": origin, "HTTP_HOST": "maverick.example", "wsgi.url_scheme": "https",
                "wsgi.input": fixtures.BytesIO(body), "CONTENT_LENGTH": str(len(body))}
            with patch("core.api.connected_accounts_api.resolve_request_session", return_value=self.f.context):
                handle_connected_accounts_api(self.f.state, environ, lambda status, headers: captured.append(status))
            self.assertTrue(captured[0].startswith(expected), captured)
        self.assertEqual(self.f.accounts.get_selection(self.f.user.user_id, "default").account_ids, [self.accounts[1].account_id])

    def test_each_broker_refreshes_its_own_account_and_removal_revokes_only_that_handle(self):
        with tempfile.TemporaryDirectory() as root:
            parsed = parse_app_contract_file(ROOT / "apps/calendar")
            invocation = AccountInvocation(identity_store=self.f.identity, workspace_store=self.f.workspace,
                secret_store=self.f.secrets, app_store=None, binding=SimpleNamespace(workspace_id="default", app_id="calendar", data_root=root),
                parsed=parsed, actor_user_id=self.f.user.user_id, payload={"data_root": root}, timeout_seconds=30)
            self.addCleanup(invocation.close)
            payload = invocation.start()
            forwarded = []
            for broker in invocation.brokers:
                broker.sender = lambda request: (forwarded.append(request.get_header("Authorization")) or (200, {}, b'{}'))
            handles = {item["account_id"]: item["access_handle"] for item in payload["external_accounts"]}
            self.assertEqual(len(set(handles.values())), 2)
            url = "https://www.googleapis.com/calendar/v3/users/me/calendarList"
            def request(account):
                with account_urlopen(Request(url, headers={"Authorization": "Bearer " + handles[account.account_id]})) as response:
                    return response.status
            def refresh(*args, **kwargs):
                return {"access_token": "access-" + kwargs["data"]["refresh_token"], "expires_in": 3600}
            with patch("core.connected_accounts.broker.google.json_request", side_effect=refresh):
                for account in self.accounts:
                    self.assertEqual(request(account), 200)
                self.assertEqual(forwarded, ["Bearer access-private-refresh-0", "Bearer access-private-refresh-1"])
                select_account(self.f.state, user_id=self.f.user.user_id, workspace_id="default", account_id=self.accounts[0].account_id)
                self.assertEqual(request(self.accounts[1]), 200)
                self.enable(self.accounts[0], enabled=False)
                with self.assertRaises(HTTPError):
                    request(self.accounts[0])
                self.assertEqual(request(self.accounts[1]), 200)

    def test_a_delayed_workspace_action_cannot_modify_a_newly_active_workspace(self):
        body = json.dumps({"workspace_id": "second", "account_id": self.accounts[0].account_id, "enabled": False}).encode()
        captured = []
        environ = {"PATH_INFO": "/api/connected-accounts/workspace-access", "REQUEST_METHOD": "POST",
            "HTTP_ORIGIN": "https://maverick.example", "HTTP_HOST": "maverick.example", "wsgi.url_scheme": "https",
            "wsgi.input": fixtures.BytesIO(body), "CONTENT_LENGTH": str(len(body))}
        with patch("core.api.connected_accounts_api.resolve_request_session", return_value=self.f.context):
            response = handle_connected_accounts_api(self.f.state, environ, lambda status, headers: captured.append(status))
        self.assertTrue(captured[0].startswith("409"), captured)
        self.assertIn("workspace_context_changed", b"".join(response).decode())
        self.assertEqual(len(self.f.accounts.get_selection(self.f.user.user_id, "default").account_ids), 2)
        self.assertIsNone(self.f.accounts.get_selection(self.f.user.user_id, "second"))

    def test_sdk_selects_exact_account_and_cannot_fall_back_to_another_handle(self):
        items = [{"provider": "google", "account_id": item.account_id, "services": ["gmail"]} for item in self.accounts]
        self.assertEqual(account_for_capability({"external_accounts": items}, "gmail", account_id=self.accounts[0].account_id), items[0])
        secrets = {"platform-google-access:platform_" + self.accounts[0].account_id: "handle-0"}
        self.assertEqual(platform_access_handle(secrets, "platform_" + self.accounts[0].account_id), "handle-0")
        with self.assertRaisesRegex(ValueError, "Enable this Google account"):
            platform_access_handle(secrets, "platform_" + self.accounts[1].account_id)
        self.assertIsNone(platform_access_handle(secrets, "manual-connection"))

    def test_concurrent_workspace_changes_preserve_other_enabled_accounts_and_app_choices(self):
        self.enable(self.accounts[0], enabled=False)
        other = replace(self.accounts[0], account_id="google_third", subject="third-subject")
        self.f.accounts.save_account(other)
        collection = self.f.accounts.collections.selections
        original_cas = collection.compare_and_set
        raced = False
        def conflict(query, update):
            nonlocal raced
            if not raced:
                raced = True
                current = self.f.accounts.get_selection(self.f.user.user_id, "default")
                self.f.accounts.save_selection(replace(current, account_ids=[*current.account_ids, other.account_id], disabled_apps=["mail"]))
                return False
            return original_cas(query, update)
        with patch.object(collection, "compare_and_set", side_effect=conflict):
            updated = self.enable(self.accounts[0])
        self.assertEqual(set(updated.account_ids), {item.account_id for item in [*self.accounts, other]})
        self.assertEqual(updated.disabled_apps, ["mail"])

    def test_private_roots_refuse_symlinks_in_shared_and_migration_paths(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            context = self.context(root)
            shared = Path(context["data_root"])
            shared.rmdir()
            shared.symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlinks"):
                self.context(root)
            shared.unlink()
            source = shared.parent / self.accounts[0].account_id
            source.symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlinks"):
                self.context(root)

    def test_all_real_app_entrypoints_project_multiple_accounts_and_withdraw_removed_access(self):
        for app, action in [("calendar", "calendar_connections.list"), ("mail", "connections.list"), ("storage", "drive_connections.list")]:
            with self.subTest(app=app), tempfile.TemporaryDirectory() as root:
                self.enable(self.accounts[0])
                source = ROOT / "apps" / app
                parsed = parse_app_contract_file(source)
                binding = SimpleNamespace(workspace_id="default", app_id=app, data_root=root)
                def invoke():
                    return run_json_entrypoint_with_sidecars(source / parsed.contract.entrypoints.backend,
                        payload={"surface": "backend", "workspace_id": "default", "app_id": app, "data_root": root,
                            "user_id": self.f.user.user_id, "body": {"action": action}, "app_secrets": {},
                            "uploaded_storage_root": str(Path(root) / "uploaded"), "generated_storage_root": str(Path(root) / "generated")},
                        cwd=source, binding=binding, parsed=parsed, surface="backend", start_path=ROOT,
                        actor_user_id=self.f.user.user_id, runtime_session_id=None,
                        identity_store=self.f.identity, workspace_store=self.f.workspace, secret_store=self.f.secrets)
                result = invoke()
                self.assertEqual(result["status_code"], 200, result)
                public = result["json"]
                items = public.get("connections", public.get("items", []))
                self.assertEqual({item["id"] for item in items if item["status"] == "connected"},
                                 {"platform_" + item.account_id for item in self.accounts}, public)
                self.assertNotIn("maverick-account:", json.dumps(public))
                select_account(self.f.state, user_id=self.f.user.user_id, workspace_id="default", account_id=self.accounts[0].account_id)
                default_result = invoke()["json"]
                default_items = default_result.get("connections", default_result.get("items", []))
                self.assertEqual(default_items[0]["id"], "platform_" + self.accounts[0].account_id)
                self.enable(self.accounts[0], enabled=False)
                result = invoke()
                self.assertEqual(result["status_code"], 200, result)
                items = result["json"].get("connections", result["json"].get("items", []))
                self.assertEqual([item["id"] for item in items if item["status"] == "connected"], ["platform_" + self.accounts[1].account_id])
