"""Session renewal must preserve logout/password-reset authority."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import json
import unittest
from unittest.mock import patch

from core.api.session_api import handle_session_api, session_payload, resolve_request_session, RequestSession
from core.identity.errors import SessionNotFoundError
from core.identity.service import build_auth_session, build_user_record, session_expiry
from core.identity.session_lifecycle import renew_auth_session
from core.identity.store import IdentityCollections, IdentityDocumentStore
from tests.support.collections import FakeCollection


class SessionLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 1, tzinfo=UTC)
        self.store = IdentityDocumentStore(IdentityCollections(FakeCollection(), FakeCollection(), FakeCollection()))
        self.session = build_auth_session(session_id="fake-login", user_id="user:test", expires_at=self.now + timedelta(days=7), now=self.now)
        self.store.save_auth_session(self.session)

    def test_new_session_has_thirty_day_idle_window(self):
        self.assertEqual(session_expiry(now=self.now), self.now + timedelta(days=30))

    def test_renewal_keeps_identity_and_is_coalesced(self):
        renewed = renew_auth_session(self.store, self.session, now=self.now)
        self.assertEqual(renewed.expires_at, self.now + timedelta(days=30))
        self.assertEqual(renewed.session_id, self.session.session_id)
        self.assertEqual(renew_auth_session(self.store, renewed, now=self.now + timedelta(hours=1)), renewed)

    def test_absolute_limit_cannot_be_extended(self):
        old = replace(self.session, created_at=self.now - timedelta(days=89))
        self.store.save_auth_session(old)
        renewed = renew_auth_session(self.store, old, now=self.now)
        self.assertEqual(renewed.expires_at, self.now + timedelta(days=1))

    def test_expired_and_revoked_sessions_are_not_renewed(self):
        for changed in (replace(self.session, status="revoked"), replace(self.session, expires_at=self.now)):
            self.store.save_auth_session(changed)
            self.assertEqual(renew_auth_session(self.store, changed, now=self.now), changed)

    def test_stale_renewal_preserves_revocation_and_deletion(self):
        revoked = replace(self.session, status="revoked")
        self.store.save_auth_session(revoked)
        self.assertEqual(renew_auth_session(self.store, self.session, now=self.now), revoked)
        self.store.delete_auth_sessions_for_user(self.session.user_id)
        with self.assertRaises(SessionNotFoundError):
            renew_auth_session(self.store, self.session, now=self.now)
        self.assertEqual(self.store.collections.auth_sessions.documents, [])

    def test_http_renewal_synchronizes_cookie_and_stable_generation(self):
        user = build_user_record(user_id="user:test", username="test", now=self.now)
        context = RequestSession(user, self.session, "default")
        captured = {}
        def start_response(status, headers):
            captured.update(status=status, headers=dict(headers))
        with patch("core.api.session_api.resolve_request_session", return_value=context), patch("core.api.session_api._now", return_value=self.now):
            body = handle_session_api(SimpleNamespace(identity_store=self.store), {"PATH_INFO": "/api/session", "wsgi.url_scheme": "https"}, start_response)
        payload = json.loads(b"".join(body))
        self.assertTrue(payload["authenticated"])
        self.assertEqual(payload["session_generation"], session_payload(context)["session_generation"])
        self.assertIn("HttpOnly", captured["headers"]["Set-Cookie"])
        self.assertIn("Secure", captured["headers"]["Set-Cookie"])
        self.assertIn("31 Oct 2026", captured["headers"]["Set-Cookie"])

    def test_absolute_expiry_is_enforced_before_user_or_workspace_lookup(self):
        old = replace(self.session, created_at=self.now - timedelta(days=91))
        self.store.save_auth_session(old)
        with patch("core.api.session_api._now", return_value=self.now):
            context = resolve_request_session(SimpleNamespace(identity_store=self.store), {"HTTP_COOKIE": "maverick_session=fake-login"})
        self.assertIsNone(context)

    def test_concurrent_revocation_returns_anonymous_without_cookie(self):
        user = build_user_record(user_id="user:test", username="test", now=self.now)
        context = RequestSession(user, self.session, "default")
        self.store.save_auth_session(replace(self.session, status="revoked"))
        headers = []
        with patch("core.api.session_api.resolve_request_session", return_value=context), patch("core.api.session_api._now", return_value=self.now):
            body = handle_session_api(SimpleNamespace(identity_store=self.store), {"PATH_INFO": "/api/session"}, lambda status, values: headers.extend(values))
        self.assertEqual(json.loads(b"".join(body)), {"authenticated": False})
        self.assertNotIn("Set-Cookie", dict(headers))

    def test_isolated_frame_cannot_receive_or_extend_platform_cookie(self):
        user = build_user_record(user_id="user:test", username="test", now=self.now)
        context = RequestSession(user, self.session, "default")
        headers = []
        with patch("core.api.session_api.resolve_request_session", return_value=context):
            handle_session_api(SimpleNamespace(identity_store=self.store), {"PATH_INFO": "/api/session", "maverick.app_frame_proxy": True}, lambda status, values: headers.extend(values))
        self.assertNotIn("Set-Cookie", dict(headers))
        self.assertEqual(self.store.get_auth_session(self.session.session_id), self.session)
