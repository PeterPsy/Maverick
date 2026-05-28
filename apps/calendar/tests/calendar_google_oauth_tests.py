from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse

from core.shared.entrypoints import run_json_entrypoint


APP_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = APP_ROOT / "backend"
TEST_CLIENT_ID = "<redacted-google-client-id>"
TEST_CLIENT_SECRET = "<redacted-google-client-secret>"
TEST_OFFLINE_GRANT = "<redacted-google-offline-grant>"
TEST_RESOURCE_REFRESH_TOKEN = "<redacted-calendar-refresh-token>"
GOOGLE_EVENTS_SCOPE = "https://www.googleapis.com/auth/calendar.events"
GOOGLE_CALENDAR_LIST_SCOPE = "https://www.googleapis.com/auth/calendar.calendarlist.readonly"


class CalendarGoogleOAuthTest(unittest.TestCase):
    def test_provider_status_and_start_oauth_create_pending_connection(self) -> None:
        fixed_now = datetime.now(UTC)
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            missing_status, missing = _handle_action(data_root, {"action": "calendar_connections.provider_status"})
            status_code, started = _handle_action(
                data_root,
                {"action": "calendar_connections.start_oauth"},
                app_id="calendar",
                app_secrets={"google-oauth-client-id": "client-id"},
                oauth_now=fixed_now,
            )
            listed_status, listed = _handle_action(data_root, {"action": "calendar_connections.list"})

        self.assertEqual(missing_status, 200)
        self.assertEqual(missing["status"], "missing_grant")
        self.assertEqual(missing["missing_secrets"], ["google-oauth-client-id", "google-oauth-client-secret"])
        self.assertEqual(status_code, 200)
        query = parse_qs(urlparse(started["authorization_url"]).query)
        self.assertEqual(query["client_id"], ["client-id"])
        self.assertEqual(query["redirect_uri"], ["/apps/calendar/oauth/callback"])
        self.assertEqual(query["access_type"], ["offline"])
        self.assertEqual(query["prompt"], ["consent"])
        requested_scopes = query["scope"][0].split()
        self.assertIn(GOOGLE_EVENTS_SCOPE, requested_scopes)
        self.assertIn(GOOGLE_CALENDAR_LIST_SCOPE, requested_scopes)
        self.assertEqual(started["state"], query["state"][0])
        self.assertEqual(started["connection"]["status"], "pending")
        self.assertNotIn("oauth_state_hash", started["connection"]["external_refs"])
        self.assertEqual(listed_status, 200)
        self.assertEqual(listed["connections"][0]["status"], "pending")

    def test_complete_oauth_updates_connection_and_returns_resource_scoped_secret_write(self) -> None:
        fixed_now = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
        calls: list[tuple[str, str, dict[str, object]]] = []

        def transport(method: str, url: str, request: dict[str, object]) -> tuple[int, dict[str, object]]:
            calls.append((method, url, request))
            if url == "https://oauth2.googleapis.com/token":
                return 200, {
                    "access_token": "access-token",
                    "refresh_token": TEST_OFFLINE_GRANT,
                    "scope": f"{GOOGLE_EVENTS_SCOPE} {GOOGLE_CALENDAR_LIST_SCOPE} openid email",
                    "token_type": "Bearer",
                }
            if url == "https://www.googleapis.com/oauth2/v2/userinfo":
                return 200, {"email": "ana@example.com", "name": "Ana Example", "id": "google-subject"}
            raise AssertionError(f"Unexpected OAuth request: {method} {url}")

        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            _status, started = _handle_action(
                data_root,
                {"action": "calendar_connections.start_oauth"},
                app_id="calendar",
                app_secrets={"google-oauth-client-id": "client-id"},
                oauth_now=fixed_now,
            )
            status_code, completed = _handle_action(
                data_root,
                {
                    "action": "calendar_connections.complete_oauth",
                    "code": "oauth-code",
                    "state": started["state"],
                },
                app_id="calendar",
                app_secrets={
                    "google-oauth-client-id": TEST_CLIENT_ID,
                    "google-oauth-client-secret": TEST_CLIENT_SECRET,
                },
                allow_platform_secret_writes=True,
                oauth_transport=transport,
                oauth_now=fixed_now + timedelta(seconds=30),
            )
            persisted = json.loads((data_root / "state.json").read_text(encoding="utf-8"))

        self.assertEqual(status_code, 200)
        connection = completed["connection"]
        self.assertEqual(connection["status"], "connected")
        self.assertEqual(connection["account_id"], "ana@example.com")
        self.assertEqual(connection["account_label"], "Ana Example")
        self.assertEqual(connection["scopes"], [GOOGLE_EVENTS_SCOPE, GOOGLE_CALENDAR_LIST_SCOPE, "openid", "email"])
        self.assertNotIn("refresh_token", str(completed["connection"]))
        self.assertEqual(
            completed["platform_secret_writes"],
            [
                {
                    "logical_name": "google-calendar-refresh-token",
                    "resource_type": "calendar_connection",
                    "resource_id": connection["id"],
                    "raw_value": TEST_OFFLINE_GRANT,
                }
            ],
        )
        self.assertEqual(persisted["connections"][0]["status"], "connected")
        self.assertNotIn(TEST_OFFLINE_GRANT, json.dumps(persisted, sort_keys=True))
        self.assertNotIn("oauth_state_hash", persisted["connections"][0]["external_refs"])
        self.assertEqual(calls[0][0], "POST")
        self.assertEqual(calls[1][0], "GET")

    def test_complete_oauth_rejects_tokens_missing_calendar_list_scope(self) -> None:
        fixed_now = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)

        def missing_calendar_list_transport(method: str, url: str, request: dict[str, object]) -> tuple[int, dict[str, object]]:
            if url == "https://oauth2.googleapis.com/token":
                return 200, {
                    "access_token": "access-token",
                    "refresh_token": TEST_OFFLINE_GRANT,
                    "scope": f"{GOOGLE_EVENTS_SCOPE} openid email",
                    "token_type": "Bearer",
                }
            return 200, {"email": "ana@example.com"}

        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            _status, started = _handle_action(
                data_root,
                {"action": "calendar_connections.start_oauth"},
                app_id="calendar",
                app_secrets={"google-oauth-client-id": "client-id"},
                oauth_now=fixed_now,
            )
            status_code, rejected = _handle_action(
                data_root,
                {"action": "calendar_connections.complete_oauth", "code": "oauth-code", "state": started["state"]},
                app_id="calendar",
                app_secrets={
                    "google-oauth-client-id": TEST_CLIENT_ID,
                    "google-oauth-client-secret": TEST_CLIENT_SECRET,
                },
                allow_platform_secret_writes=True,
                oauth_transport=missing_calendar_list_transport,
                oauth_now=fixed_now + timedelta(seconds=30),
            )

        self.assertEqual(status_code, 400)
        self.assertEqual(rejected["error"], "missing_calendar_scope")
        self.assertIn(GOOGLE_CALENDAR_LIST_SCOPE, rejected["detail"])

    def test_complete_oauth_without_platform_secret_write_permission_rejects_before_secret_grants(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            status_code, rejected = _handle_action(
                data_root,
                {"action": "calendar_connections.complete_oauth", "code": "oauth-code", "state": "oauth-state"},
            )

        self.assertEqual(status_code, 400)
        self.assertEqual(rejected["error"], "secret_write_unavailable")
        self.assertIn("backend callback", rejected["detail"])

    def test_complete_oauth_rejects_invalid_expired_and_missing_grant_states(self) -> None:
        fixed_now = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)

        def no_refresh_transport(method: str, url: str, request: dict[str, object]) -> tuple[int, dict[str, object]]:
            if url == "https://oauth2.googleapis.com/token":
                return 200, {
                    "access_token": "access-token",
                    "scope": f"{GOOGLE_EVENTS_SCOPE} {GOOGLE_CALENDAR_LIST_SCOPE}",
                    "token_type": "Bearer",
                }
            return 200, {"email": "ana@example.com"}

        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            invalid_status, invalid = _handle_action(
                data_root,
                {"action": "calendar_connections.complete_oauth", "state": "missing-code"},
                app_secrets={"google-oauth-client-id": TEST_CLIENT_ID, "google-oauth-client-secret": TEST_CLIENT_SECRET},
                allow_platform_secret_writes=True,
                oauth_transport=no_refresh_transport,
                oauth_now=fixed_now,
            )
            _status, started = _handle_action(
                data_root,
                {"action": "calendar_connections.start_oauth"},
                app_secrets={"google-oauth-client-id": "client-id"},
                oauth_now=fixed_now,
            )
            expired_status, expired = _handle_action(
                data_root,
                {"action": "calendar_connections.complete_oauth", "code": "oauth-code", "state": started["state"]},
                app_secrets={"google-oauth-client-id": TEST_CLIENT_ID, "google-oauth-client-secret": TEST_CLIENT_SECRET},
                allow_platform_secret_writes=True,
                oauth_transport=no_refresh_transport,
                oauth_now=fixed_now + timedelta(seconds=601),
            )
            _status, fresh = _handle_action(
                data_root,
                {"action": "calendar_connections.start_oauth"},
                app_secrets={"google-oauth-client-id": "client-id"},
                oauth_now=fixed_now,
            )
            grant_status, grant = _handle_action(
                data_root,
                {"action": "calendar_connections.complete_oauth", "code": "oauth-code", "state": fresh["state"]},
                app_secrets={"google-oauth-client-id": TEST_CLIENT_ID, "google-oauth-client-secret": TEST_CLIENT_SECRET},
                allow_platform_secret_writes=True,
                oauth_transport=no_refresh_transport,
                oauth_now=fixed_now + timedelta(seconds=30),
            )

        self.assertEqual(invalid_status, 400)
        self.assertEqual(invalid["error"], "invalid_oauth_callback")
        self.assertEqual(expired_status, 400)
        self.assertEqual(expired["error"], "expired_oauth_state")
        self.assertEqual(grant_status, 400)
        self.assertEqual(grant["error"], "missing_oauth_grant")

    def test_connection_actions_emit_connection_data_events(self) -> None:
        self.assertEqual(
            _app_events_for_action("calendar_connections.start_oauth"),
            [{"type": "maverick.app.data-changed", "owner_app_id": "calendar", "resource": "connections"}],
        )
        self.assertEqual(
            _app_events_for_action("calendar_connections.complete_oauth"),
            [{"type": "maverick.app.data-changed", "owner_app_id": "calendar", "resource": "connections"}],
        )

    def test_disconnect_revokes_google_token_and_disables_connection(self) -> None:
        fixed_now = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
        calls: list[tuple[str, str, dict[str, object]]] = []

        def transport(method: str, url: str, request: dict[str, object]) -> tuple[int, dict[str, object]]:
            calls.append((method, url, request))
            if url == "https://oauth2.googleapis.com/revoke":
                self.assertEqual(request["data"], {"token": TEST_RESOURCE_REFRESH_TOKEN})
                return 200, {}
            raise AssertionError(f"Unexpected revoke request: {method} {url}")

        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            data_root.mkdir(parents=True)
            (data_root / "state.json").write_text(
                json.dumps(
                    {
                        "schema_version": "3",
                        "events": [],
                        "connections": [
                            {
                                "id": "cal_conn_work",
                                "provider": "google",
                                "account_id": "ana@example.com",
                                "account_label": "Ana Work",
                                "status": "connected",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            status_code, disconnected = _handle_action(
                data_root,
                {"action": "calendar_connections.disconnect", "connection_id": "cal_conn_work"},
                app_secrets={"google-calendar-refresh-token": TEST_RESOURCE_REFRESH_TOKEN},
                oauth_transport=transport,
                oauth_now=fixed_now,
            )
            persisted = json.loads((data_root / "state.json").read_text(encoding="utf-8"))

        self.assertEqual(status_code, 200)
        self.assertTrue(disconnected["disconnected"])
        self.assertEqual(disconnected["connection"]["status"], "disabled")
        self.assertNotIn(TEST_RESOURCE_REFRESH_TOKEN, json.dumps(disconnected, sort_keys=True))
        self.assertEqual(persisted["connections"][0]["status"], "disabled")
        self.assertEqual(persisted["connections"][0]["external_refs"]["disconnected_at"], "2026-05-28T12:00:00Z")
        self.assertNotIn(TEST_RESOURCE_REFRESH_TOKEN, json.dumps(persisted, sort_keys=True))
        self.assertEqual(calls[0][0], "POST")

    def test_default_transport_serializes_json_request_body(self) -> None:
        google_oauth = _import_calendar_google_oauth()
        captured: dict[str, object] = {}

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback) -> bool:
                return False

            def read(self) -> bytes:
                return b'{"ok": true}'

        def fake_urlopen(request, timeout: int):
            captured["method"] = request.get_method()
            captured["url"] = request.full_url
            captured["data"] = request.data
            captured["headers"] = dict(request.header_items())
            captured["timeout"] = timeout
            return Response()

        original_urlopen = google_oauth.urlopen
        google_oauth.urlopen = fake_urlopen
        try:
            status, payload = google_oauth.default_transport(
                "PATCH",
                "https://www.googleapis.com/calendar/v3/calendars/primary/events/event-1",
                {
                    "headers": {"content-type": "application/json", "authorization": "Bearer access-token"},
                    "json": {"summary": "Focus", "attendees": [{"email": "ana@example.com"}]},
                },
            )
        finally:
            google_oauth.urlopen = original_urlopen
            _cleanup_calendar_backend_modules()

        self.assertEqual(status, 200)
        self.assertEqual(payload, {"ok": True})
        self.assertEqual(captured["method"], "PATCH")
        self.assertEqual(captured["timeout"], 15)
        self.assertEqual(
            json.loads(captured["data"].decode("utf-8")),
            {"summary": "Focus", "attendees": [{"email": "ana@example.com"}]},
        )
        self.assertEqual(captured["headers"]["Content-type"], "application/json")

    def test_cli_and_mcp_entrypoints_forward_core_secrets_to_oauth_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            cli_result = run_json_entrypoint(
                APP_ROOT / "cli" / "app_cli.py",
                cwd=APP_ROOT,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "command_id": "app.calendar.calendar",
                    "app_secrets": {"google-oauth-client-id": "client-id"},
                    "arguments": {"action": "calendar_connections.start_oauth"},
                },
            )
            mcp_result = run_json_entrypoint(
                APP_ROOT / "mcp" / "server.py",
                cwd=APP_ROOT,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_connections.start_oauth",
                    "app_secrets": {"google-oauth-client-id": "client-id"},
                    "arguments": {},
                },
            )
            mcp_complete_result = run_json_entrypoint(
                APP_ROOT / "mcp" / "server.py",
                cwd=APP_ROOT,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_connections.complete_oauth",
                    "app_secrets": {
                        "google-oauth-client-id": TEST_CLIENT_ID,
                        "google-oauth-client-secret": TEST_CLIENT_SECRET,
                    },
                    "arguments": {"code": "oauth-code", "state": "oauth-state"},
                },
            )

        self.assertEqual(cli_result["status_code"], 200)
        self.assertIn("client_id=client-id", cli_result["authorization_url"])
        self.assertEqual(mcp_result["status_code"], 200)
        self.assertIn("client_id=client-id", mcp_result["authorization_url"])
        self.assertEqual(mcp_complete_result["status_code"], 404)
        self.assertEqual(mcp_complete_result["error"], "unsupported_tool")


def _handle_action(data_root: Path, body: dict[str, object], **kwargs):
    actions = _import_calendar_actions()
    try:
        return actions.handle_action(data_root, body, **kwargs)
    finally:
        _cleanup_calendar_backend_modules()


def _app_events_for_action(action: str):
    actions = _import_calendar_actions()
    try:
        return actions.app_events_for_action(action)
    finally:
        _cleanup_calendar_backend_modules()


def _import_calendar_actions():
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    import actions

    return actions


def _import_calendar_google_oauth():
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    import google_oauth

    return google_oauth


def _cleanup_calendar_backend_modules() -> None:
    sys.path[:] = [item for item in sys.path if item != str(BACKEND_ROOT)]
    for module_name, module in list(sys.modules.items()):
        module_file = getattr(module, "__file__", "")
        if module_file and str(module_file).startswith(str(BACKEND_ROOT)):
            sys.modules.pop(module_name, None)


if __name__ == "__main__":
    unittest.main()
