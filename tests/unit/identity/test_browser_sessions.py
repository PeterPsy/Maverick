"""Delegated browser authentication must remain bounded to its live actor."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.api.session_api import RequestSession, handle_session_api, resolve_request_session
from core.identity.browser_sessions import browser_session_is_current, issue_platform_browser_session, platform_browser_origin
from core.identity.service import build_auth_session, build_user_record
from core.identity.session_lifecycle import renew_auth_session
from core.identity.store import IdentityCollections, IdentityDocumentStore
from tests.support.collections import FakeCollection


class BrowserSessionTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 10, tzinfo=UTC)
        self.identity = IdentityDocumentStore(IdentityCollections(FakeCollection(), FakeCollection(), FakeCollection()))
        self.user = build_user_record(user_id="user:test", username="test", now=self.now)
        self.identity.save_user(self.user)
        self.login = build_auth_session(session_id="human-login", user_id=self.user.user_id,
                                       expires_at=self.now + timedelta(days=30), now=self.now)
        self.identity.save_auth_session(self.login)
        self.runtime = SimpleNamespace(owner_user_id=self.user.user_id, workspace_id="default", ended_at=None, status="running")
        self.runtime_store = SimpleNamespace(get_session=lambda session_id: self.runtime)
        self.workspace = SimpleNamespace(workspace_id="default")
        self.selection_patch = patch("core.identity.browser_sessions.resolve_active_workspace_for_user", side_effect=lambda *args, **kwargs: self.workspace)
        self.selection_patch.start()
        self.addCleanup(self.selection_patch.stop)
        self.origin_patch = patch.dict("os.environ", {"MAVERICK_SIDECAR_PLATFORM_ORIGIN": "http://maverick.localhost:8014"})
        self.origin_patch.start()
        self.addCleanup(self.origin_patch.stop)
        self.grant = self.issue()
        self.session = self.identity.get_auth_session(self.grant["cookie_value"])

    def issue(self):
        return issue_platform_browser_session(self.identity, object(), self.runtime_store, user_id=self.user.user_id,
                                               workspace_id="default", runtime_session_id="runtime:test", now=self.now)

    def current(self, session=None, **kwargs):
        return browser_session_is_current(self.identity, object(), self.runtime_store, session or self.session,
                                           now=self.now, **kwargs)

    def test_separate_agents_get_separate_fixed_expiry_logins(self):
        second = self.issue()
        self.assertNotEqual(second["cookie_value"], self.grant["cookie_value"])
        self.assertEqual(self.session.expires_at, self.now + timedelta(hours=4))
        self.assertTrue(self.current())
        self.assertEqual(renew_auth_session(self.identity, self.session, now=self.now), self.session)
        self.assertEqual(self.identity.get_auth_session(self.login.session_id), self.login)

    def test_origin_runtime_owner_and_workspace_are_rechecked(self):
        self.assertFalse(self.current(origin="http://hostmachine:8014"))
        self.assertFalse(self.current(replace(self.session, browser_workspace_id="another")))
        self.assertFalse(self.current(replace(self.session, expires_at=self.now + timedelta(hours=5))))
        for field, value in (("owner_user_id", "another-user"), ("workspace_id", "another"),
                             ("ended_at", self.now), ("status", "recovery_required")):
            previous = getattr(self.runtime, field)
            setattr(self.runtime, field, value)
            self.assertFalse(self.current(), field)
            setattr(self.runtime, field, previous)
        self.workspace = SimpleNamespace(workspace_id="another")
        self.assertFalse(self.current())
        with self.assertRaisesRegex(ValueError, "authentication_unavailable"):
            self.issue()

    def test_logout_new_login_and_password_reset_invalidate_browser_login(self):
        self.identity.save_auth_session(replace(self.login, status="revoked"))
        self.assertFalse(self.current())
        self.identity.save_auth_session(self.login)
        self.assertTrue(self.current())
        self.identity.save_auth_session(replace(self.login, session_id="second-human-login"))
        self.assertFalse(self.current())
        self.identity.delete_auth_sessions_for_user(self.user.user_id)
        self.assertFalse(self.current())

    def test_http_session_cannot_extend_browser_login_and_logout_preserves_human_login(self):
        context = RequestSession(self.user, self.session, "default")
        frames = Mock()
        state = SimpleNamespace(identity_store=self.identity, sidecar_browser_sessions=frames, device_use_service=Mock())
        with patch("core.api.session_api.resolve_request_session", return_value=context), patch("core.api.session_api._now", return_value=self.now):
            headers = []
            body = handle_session_api(state, {"PATH_INFO": "/api/session"}, lambda status, values: headers.extend(values))
            self.assertTrue(json.loads(b"".join(body))["authenticated"])
            self.assertEqual(self.identity.get_auth_session(self.session.session_id).expires_at, self.session.expires_at)
            handle_session_api(state, {"PATH_INFO": "/api/auth/logout", "REQUEST_METHOD": "POST"}, lambda *args: None)
        frames.revoke_platform_session.assert_called_once_with(self.session.session_id)
        frames.revoke_actor.assert_not_called()
        state.device_use_service.stop_auth_session.assert_not_called()
        self.assertEqual(self.identity.get_auth_session(self.login.session_id), self.login)
        self.assertEqual(self.identity.get_auth_session(self.session.session_id).status, "revoked")

    def test_http_identity_resolution_requires_exact_origin(self):
        state = SimpleNamespace(identity_store=self.identity, runtime_store=self.runtime_store, workspace_store=object())
        env = {"HTTP_COOKIE": f"maverick_session={self.session.session_id}", "wsgi.url_scheme": "http", "HTTP_HOST": "maverick.localhost:8014"}
        with patch("core.api.session_api._now", return_value=self.now), patch("core.api.session_api.resolve_active_workspace_for_user", return_value=self.workspace):
            self.assertIsNotNone(resolve_request_session(state, env))
            self.assertIsNone(resolve_request_session(state, {**env, "HTTP_HOST": "hostmachine:8014"}))

    def test_local_origin_uses_running_api_port(self):
        with patch.dict("os.environ", {"MAVERICK_SIDECAR_PLATFORM_ORIGIN": "", "MAVERICK_API_BASE": "http://127.0.0.1:8123"}):
            self.assertEqual(platform_browser_origin(), "http://maverick.localhost:8123")

    def test_websocket_authentication_uses_the_equivalent_http_origin(self):
        state = SimpleNamespace(identity_store=self.identity, runtime_store=self.runtime_store, workspace_store=object())
        for scheme, origin, host in (("ws", "http://maverick.localhost:8014", "maverick.localhost:8014"),
                                    ("wss", "https://maverick.example", "maverick.example")):
            self.identity.save_auth_session(replace(self.session, browser_origin=origin))
            env = {"HTTP_COOKIE": f"maverick_session={self.session.session_id}", "wsgi.url_scheme": scheme, "HTTP_HOST": host}
            with patch("core.api.session_api._now", return_value=self.now), patch("core.api.session_api.resolve_active_workspace_for_user", return_value=self.workspace):
                self.assertIsNotNone(resolve_request_session(state, env), scheme)
                self.assertIsNone(resolve_request_session(state, {**env, "HTTP_HOST": "another.example"}), scheme)


if __name__ == "__main__":
    unittest.main()
