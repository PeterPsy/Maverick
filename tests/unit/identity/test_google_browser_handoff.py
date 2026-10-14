"""Regression coverage for independent native and system-browser cookie jars."""

from dataclasses import replace
from datetime import timedelta
from io import BytesIO
from contextlib import redirect_stdout
from io import StringIO
import json
from http.cookies import SimpleCookie
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit
from threading import Thread
from wsgiref.simple_server import WSGIRequestHandler, make_server

from tests.unit.identity import test_connected_accounts as fixtures
from core.api.connected_accounts_api import handle_connected_accounts_api
from core.connected_accounts.service import digest


class GoogleBrowserHandoffTests(unittest.TestCase):
    def setUp(self):
        fixtures.ConnectedAccountsTests.setUp(self)
        self.identity.save_auth_session(self.context.session)
        self.native = {"loopino_session": self.context.session.session_id}
        self.browser = {}
        self.tokens = patch("core.connected_accounts.google.json_request", return_value={
            "id_token": "provider-signed-id", "scope": "openid email profile", "refresh_token": "provider-refresh"})
        self.claims = patch("core.connected_accounts.service.verify_identity", return_value={
            "sub": "google-alice", "email": "alice@example.com", "name": "Alice"})
        self.tokens.start(); self.claims.start()
        self.addCleanup(self.tokens.stop); self.addCleanup(self.claims.stop)

    def request(self, path, *, jar=None, body=None, query=None, origin="https://loopino.example", proxy=False):
        jar = self.native if jar is None else jar
        data = json.dumps(body).encode() if body is not None else b""
        environ = {"PATH_INFO": path, "REQUEST_METHOD": "POST" if body is not None else "GET",
            "HTTP_HOST": "loopino.example", "wsgi.url_scheme": "https", "HTTP_ORIGIN": origin,
            "HTTP_COOKIE": "; ".join(f"{key}={value}" for key, value in jar.items()),
            "QUERY_STRING": urlencode(query or {}), "wsgi.input": BytesIO(data), "CONTENT_LENGTH": str(len(data)),
            "CONTENT_TYPE": "application/json", "loopino.app_frame_proxy": proxy}
        captured = {}
        def respond(status, headers): captured.update(status=status, headers=headers)
        content = b"".join(handle_connected_accounts_api(self.state, environ, respond))
        for key, value in captured["headers"]:
            if key.lower() == "set-cookie":
                cookie = SimpleCookie(value)
                for name, item in cookie.items():
                    if item.value: jar[name] = item.value
                    else: jar.pop(name, None)
        captured["body"] = json.loads(content) if content else None
        return captured

    def start(self, mode="connect"):
        response = self.request("/api/auth/google/start", body={"mode": mode, "services": [], "transport": "system-browser"})
        self.assertEqual(response["status"], "200 OK")
        result = response["body"]
        raw_state, handoff = urlsplit(result["browser_url"]).fragment.split(".")
        self.assertEqual(result["flow_id"], digest(raw_state))
        self.assertNotIn(handoff, urlsplit(result["browser_url"]).query)
        return result["flow_id"], raw_state, handoff

    def launch(self, raw_state, handoff):
        response = self.request("/api/auth/google/handoff", jar=self.browser, body={"state": raw_state, "handoff": handoff})
        self.assertEqual(response["status"], "200 OK")
        return parse_qs(urlsplit(response["body"]["authorization_url"]).query)

    def callback(self, raw_state, *, error=None):
        return self.request("/api/auth/google/callback", jar=self.browser,
            query={"state": raw_state, **({"error": error} if error else {"code": "provider-code"})})

    def test_native_connection_completes_with_independent_browser_cookies(self):
        flow_id, raw_state, handoff = self.start()
        native_cookie = self.native["loopino_google_flow"]
        self.assertEqual(self.request("/api/auth/google/result", body={"flow_id": flow_id})["body"], {"status": "pending"})
        query = self.launch(raw_state, handoff)
        self.assertNotEqual(native_cookie, self.browser["loopino_google_flow"])
        self.assertEqual(query["nonce"], [digest(self.browser["loopino_google_flow"])])
        self.assertEqual(self.callback(raw_state)["status"], "303 See Other")
        self.assertEqual(len(self.accounts.list_accounts(self.user.user_id)), 1)
        self.assertNotIn("loopino_session", self.browser)
        result = self.request("/api/auth/google/result", body={"flow_id": flow_id})
        self.assertEqual(result["body"], {"status": "completed"})
        self.assertEqual(self.native["loopino_session"], self.context.session.session_id)
        self.assertNotIn("loopino_google_flow", self.native)

    def test_handoff_and_receipt_are_one_use_and_store_no_raw_secrets(self):
        flow_id, raw_state, handoff = self.start()
        metadata = repr(self.accounts.collections.flows.find({}))
        for secret in [raw_state, handoff, self.native["loopino_google_flow"], self.context.session.session_id]:
            self.assertNotIn(secret, metadata)
        self.launch(raw_state, handoff)
        replay = self.request("/api/auth/google/handoff", jar={}, body={"state": raw_state, "handoff": handoff})
        self.assertEqual(replay["body"]["error"], "google_flow_invalid")
        self.callback(raw_state)
        original = dict(self.native)
        self.request("/api/auth/google/result", body={"flow_id": flow_id})
        self.assertEqual(self.request("/api/auth/google/result", jar=original, body={"flow_id": flow_id})["body"]["error"], "google_flow_invalid")

    def test_wrong_or_missing_external_cookie_does_not_complete_connection(self):
        flow_id, raw_state, handoff = self.start()
        self.launch(raw_state, handoff)
        for jar in [{}, self.native, {"loopino_google_flow": "wrong"}]:
            response = self.request("/api/auth/google/callback", jar=dict(jar), query={"state": raw_state, "code": "code"})
            self.assertIn("google_flow_invalid", dict(response["headers"])["Location"])
        self.assertFalse(self.accounts.list_accounts(self.user.user_id))
        self.assertEqual(self.accounts.get_flow(flow_id).status, "pending")

    def test_receipt_requires_original_webview_cookie(self):
        flow_id, raw_state, handoff = self.start()
        self.launch(raw_state, handoff)
        external_cookie = dict(self.browser)
        self.callback(raw_state)
        for jar in [{}, external_cookie, {"loopino_session": self.context.session.session_id}]:
            result = self.request("/api/auth/google/result", jar=jar, body={"flow_id": flow_id})
            self.assertEqual(result["body"]["error"], "google_flow_invalid")
        self.assertEqual(self.accounts.get_flow(flow_id).status, "completed")

    def test_revoked_source_session_blocks_launch_and_callback(self):
        for stage in ["launch", "callback"]:
            self.identity.save_auth_session(self.context.session)
            flow_id, raw_state, handoff = self.start()
            if stage == "callback": self.launch(raw_state, handoff)
            self.identity.save_auth_session(replace(self.context.session, status="revoked"))
            if stage == "launch":
                response = self.request("/api/auth/google/handoff", jar={}, body={"state": raw_state, "handoff": handoff})
                self.assertEqual(response["body"]["error"], "google_flow_session_changed")
            else:
                response = self.callback(raw_state)
                self.assertIn("google_flow_session_changed", dict(response["headers"])["Location"])
                self.assertEqual(self.accounts.get_flow(flow_id).result_error, "google_flow_session_changed")
        self.assertFalse(self.accounts.list_accounts(self.user.user_id))

    def test_cancelled_consent_reaches_original_webview(self):
        flow_id, raw_state, handoff = self.start()
        self.launch(raw_state, handoff)
        response = self.callback(raw_state, error="access_denied")
        self.assertIn("google_handoff_done=1", dict(response["headers"])["Location"])
        self.assertEqual(self.request("/api/auth/google/result", body={"flow_id": flow_id})["body"],
                         {"status": "failed", "error": "google_consent_cancelled"})

    def test_callback_replay_cannot_overwrite_a_result_in_progress(self):
        flow_id, raw_state, handoff = self.start()
        self.launch(raw_state, handoff)
        cookie = self.browser["loopino_google_flow"]
        flow = self.accounts.consume_flow(flow_id, digest(cookie), self.now)
        self.assertIsNotNone(flow)
        response = self.callback(raw_state, error="access_denied")
        self.assertIn("google_flow_invalid", dict(response["headers"])["Location"])
        self.assertEqual(self.accounts.get_flow(flow_id).status, "consumed")
        from core.connected_accounts.browser_handoff import finish
        finish(self.state, flow, user_id=self.user.user_id, workspace_id="default")
        self.assertEqual(self.request("/api/auth/google/result", body={"flow_id": flow_id})["body"], {"status": "completed"})

    def test_removed_membership_and_inactive_user_block_handoff(self):
        flow_id, raw_state, handoff = self.start()
        membership = self.workspace.list_memberships_for_user(self.user.user_id)[0]
        self.workspace.save_membership(replace(membership, status="inactive"))
        response = self.request("/api/auth/google/handoff", jar={}, body={"state": raw_state, "handoff": handoff})
        self.assertEqual(response["body"]["error"], "google_flow_session_changed")
        self.workspace.save_membership(membership)
        self.identity.save_user(replace(self.user, is_active=False))
        response = self.request("/api/auth/google/handoff", jar={}, body={"state": raw_state, "handoff": handoff})
        self.assertEqual(response["body"]["error"], "google_flow_session_changed")
        self.assertEqual(self.accounts.get_flow(flow_id).status, "awaiting_browser")

    def test_new_source_session_cannot_collect_an_older_connection(self):
        flow_id, raw_state, handoff = self.start()
        self.launch(raw_state, handoff); self.callback(raw_state)
        newer = replace(self.context.session, session_id="new-alice-session")
        self.identity.save_auth_session(newer)
        wrong_session = {**self.native, "loopino_session": newer.session_id}
        response = self.request("/api/auth/google/result", jar=wrong_session, body={"flow_id": flow_id})
        self.assertEqual(response["body"]["error"], "google_flow_session_changed")
        self.assertEqual(self.accounts.get_flow(flow_id).status, "completed")

    def test_browser_signed_into_another_user_does_not_change_account_owner(self):
        other = self.identity.save_user(fixtures.build_user_record(user_id="user:bob", username="bob", email="bob@example.com"))
        fixtures.ensure_workspace_membership(self.workspace, membership_id="bob-default", workspace_id="default", user_id=other.user_id, role="member")
        session = self.identity.save_auth_session(fixtures.build_auth_session(session_id="session-bob", user_id=other.user_id,
                                                                              expires_at=self.now + timedelta(days=1)))
        self.browser["loopino_session"] = session.session_id
        flow_id, raw_state, handoff = self.start()
        self.launch(raw_state, handoff); self.callback(raw_state)
        self.assertEqual(self.browser["loopino_session"], session.session_id)
        self.assertEqual(len(self.accounts.list_accounts(self.user.user_id)), 1)
        self.assertFalse(self.accounts.list_accounts(other.user_id))
        self.assertEqual(self.request("/api/auth/google/result", body={"flow_id": flow_id})["body"], {"status": "completed"})

    def test_local_cancel_prevents_late_callback(self):
        flow_id, raw_state, handoff = self.start()
        self.launch(raw_state, handoff)
        self.assertEqual(self.request("/api/auth/google/cancel", body={"flow_id": flow_id})["body"], {"status": "cancelled"})
        self.assertIn("google_flow_invalid", dict(self.callback(raw_state)["headers"])["Location"])
        self.assertFalse(self.accounts.list_accounts(self.user.user_id))

    def test_login_cookie_is_issued_only_to_original_native_webview(self):
        # Establish an explicitly linked identity using an ordinary connect.
        query, cookie = fixtures.ConnectedAccountsTests.flow(self)
        fixtures.ConnectedAccountsTests.complete(self, query, cookie, subject="google-alice", scopes=[])
        self.native = {}
        flow_id, raw_state, handoff = self.start("login")
        self.launch(raw_state, handoff)
        callback = self.callback(raw_state)
        self.assertFalse(any("loopino_session=" in value for _, value in callback["headers"]))
        result = self.request("/api/auth/google/result", body={"flow_id": flow_id})
        self.assertEqual(result["body"], {"status": "completed"})
        self.assertIn("loopino_session", self.native)
        session = self.identity.get_auth_session(self.native["loopino_session"])
        self.assertEqual(session.user_id, self.user.user_id)
        self.assertNotIn(session.session_id, repr(result["body"]))

    def test_expired_and_cross_origin_flows_are_rejected(self):
        flow_id, raw_state, handoff = self.start()
        for path, body in [("/api/auth/google/handoff", {"state": raw_state, "handoff": handoff}),
                           ("/api/auth/google/result", {"flow_id": flow_id}), ("/api/auth/google/cancel", {"flow_id": flow_id})]:
            for origin, proxy in [("https://evil.example", False), ("https://loopino.example", True)]:
                self.assertEqual(self.request(path, body=body, origin=origin, proxy=proxy)["status"], "403 Forbidden")
        flow = self.accounts.get_flow(flow_id)
        self.accounts.save_flow(replace(flow, expires_at=self.now - timedelta(seconds=1)))
        result = self.request("/api/auth/google/result", body={"flow_id": flow_id})
        self.assertEqual(result["body"]["error"], "google_flow_invalid")

    def test_deployment_smoke_exercises_real_http_cookie_jars(self):
        from scripts.google_accounts_smoke import run
        class QuietHandler(WSGIRequestHandler):
            def log_message(self, *args): pass
        server = make_server("127.0.0.1", 0,
            lambda environ, response: handle_connected_accounts_api(self.state, environ, response), handler_class=QuietHandler)
        origin = f"http://127.0.0.1:{server.server_port}"
        thread = Thread(target=server.serve_forever)
        thread.start()
        try:
            with patch.dict("os.environ", {"LOOPINO_GOOGLE_REDIRECT_URI": origin + "/api/auth/google/callback"}), redirect_stdout(StringIO()) as output:
                run(origin)
            self.assertIn("original native session receives the cancelled result", output.getvalue())
            self.assertNotIn("provider-refresh", output.getvalue())
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)


if __name__ == "__main__": unittest.main()
