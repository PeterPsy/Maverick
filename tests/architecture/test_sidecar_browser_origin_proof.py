"""G1 feasibility proof for an isolated browser origin and POST bootstrap."""

from __future__ import annotations

from hashlib import sha256
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import socket
import threading
import time
from urllib.parse import parse_qs
import unittest


SIDECAR_HOST = "proof-instance.sidecars.localhost"
SIDECAR_ORIGIN = f"http://{SIDECAR_HOST}"
COOKIE_NAME = "maverick_sidecar_session"


class _ProofState:
    def __init__(self) -> None:
        self.ticket_hashes: dict[str, float] = {}
        self.session_hashes: set[str] = set()
        self.audit_paths: list[str] = []

    def issue_ticket(self) -> str:
        ticket = secrets.token_urlsafe(32)
        self.ticket_hashes[_digest(ticket)] = time.monotonic() + 30
        return ticket

    def consume_ticket(self, ticket: str) -> bool:
        digest = _digest(ticket)
        expires_at = self.ticket_hashes.pop(digest, 0)
        return expires_at >= time.monotonic()

    def issue_session(self) -> str:
        session = secrets.token_urlsafe(32)
        self.session_hashes.add(_digest(session))
        return session

    def valid_session(self, value: str) -> bool:
        return _digest(value) in self.session_hashes


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


class _ProofHandler(BaseHTTPRequestHandler):
    server: "_ProofServer"

    def do_POST(self) -> None:
        self.server.state.audit_paths.append(self.path)
        if self.headers.get("Host") != SIDECAR_HOST:
            self._json(421, {"error": "wrong_host"})
            return
        if self.path == "/.well-known/maverick-sidecar-bootstrap":
            payload = self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode("utf-8")
            ticket = parse_qs(payload).get("ticket", [""])[0]
            if not self.server.state.consume_ticket(ticket):
                self._json(410, {"error": "ticket_expired_or_spent"})
                return
            session = self.server.state.issue_session()
            self.send_response(303)
            self.send_header("Location", "/")
            self.send_header(
                "Set-Cookie",
                f"{COOKIE_NAME}={session}; Path=/; HttpOnly; SameSite=Strict",
            )
            self._security_headers()
            self.end_headers()
            return
        if not self._authorized():
            self._json(401, {"error": "sidecar_session_required"})
            return
        if self.headers.get("Origin") != SIDECAR_ORIGIN:
            self._json(403, {"error": "origin_denied"})
            return
        if self.headers.get("Sec-Fetch-Site") != "same-origin":
            self._json(403, {"error": "fetch_metadata_denied"})
            return
        if self.path == "/api/projects":
            self._json(200, {"surface": "opendesign", "projects": []})
            return
        self._json(404, {"error": "route_not_declared"})

    def do_GET(self) -> None:
        self.server.state.audit_paths.append(self.path)
        if self.headers.get("Host") != SIDECAR_HOST or not self._authorized():
            self._json(401, {"error": "sidecar_session_required"})
            return
        if self.path == "/api/projects":
            self._json(200, {"surface": "opendesign", "projects": []})
            return
        self._json(404, {"error": "route_not_declared"})

    def _authorized(self) -> bool:
        cookies = {}
        for item in self.headers.get("Cookie", "").split(";"):
            name, separator, value = item.strip().partition("=")
            if separator:
                cookies[name] = value
        return self.server.state.valid_session(cookies.get(COOKIE_NAME, ""))

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _security_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; connect-src 'self'; frame-ancestors http://localhost",
        )

    def log_message(self, format: str, *args: object) -> None:
        return


class _ProofServer(ThreadingHTTPServer):
    def __init__(self, state: _ProofState) -> None:
        super().__init__(("127.0.0.1", 0), _ProofHandler)
        self.state = state


class SidecarBrowserOriginDecisionProof(unittest.TestCase):
    def test_local_post_bootstrap_is_one_shot_clean_and_origin_isolated(self) -> None:
        addresses = socket.getaddrinfo(SIDECAR_HOST, 80, type=socket.SOCK_STREAM)
        self.assertTrue(any(address[4][0] in {"127.0.0.1", "::1"} for address in addresses))

        state = _ProofState()
        server = _ProofServer(state)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        ticket = state.issue_ticket()

        bootstrap = self._request(
            server,
            "POST",
            "/.well-known/maverick-sidecar-bootstrap",
            body=f"ticket={ticket}",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Cookie": "maverick_session=must-not-cross",
            },
        )
        self.assertEqual(bootstrap[0], 303)
        self.assertEqual(bootstrap[1]["location"], "/")
        self.assertEqual(bootstrap[1]["cache-control"], "no-store")
        self.assertEqual(bootstrap[1]["referrer-policy"], "no-referrer")
        self.assertIn("frame-ancestors http://localhost", bootstrap[1]["content-security-policy"])
        self.assertNotIn(ticket, json.dumps(bootstrap[1]))
        self.assertNotIn(ticket, "\n".join(state.audit_paths))
        cookie = bootstrap[1]["set-cookie"]
        self.assertIn(f"{COOKIE_NAME}=", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertNotIn("Domain=", cookie)
        self.assertNotIn(ticket, cookie)
        sidecar_cookie = cookie.split(";", 1)[0]

        host_bound_ticket = state.issue_ticket()
        wrong_host = self._request(
            server,
            "POST",
            "/.well-known/maverick-sidecar-bootstrap",
            body=f"ticket={host_bound_ticket}",
            headers={"Host": "another.sidecars.localhost"},
        )
        self.assertEqual(wrong_host[0], 421)

        replay = self._request(
            server,
            "POST",
            "/.well-known/maverick-sidecar-bootstrap",
            body=f"ticket={ticket}",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        self.assertEqual(replay[0], 410)

        projects = self._request(
            server,
            "GET",
            "/api/projects",
            headers={"Cookie": sidecar_cookie},
        )
        self.assertEqual(projects[0], 200)
        self.assertEqual(json.loads(projects[2])["surface"], "opendesign")

        core_route = self._request(
            server,
            "GET",
            "/api/status",
            headers={"Cookie": sidecar_cookie},
        )
        self.assertEqual(core_route[0], 404)

        missing_origin = self._request(
            server,
            "POST",
            "/api/projects",
            body="{}",
            headers={"Cookie": sidecar_cookie, "Content-Type": "application/json"},
        )
        self.assertEqual(missing_origin[0], 403)
        same_origin = self._request(
            server,
            "POST",
            "/api/projects",
            body="{}",
            headers={
                "Cookie": sidecar_cookie,
                "Content-Type": "application/json",
                "Origin": SIDECAR_ORIGIN,
                "Sec-Fetch-Site": "same-origin",
            },
        )
        self.assertEqual(same_origin[0], 200)

    def _request(
        self,
        server: _ProofServer,
        method: str,
        path: str,
        *,
        body: str = "",
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        request_headers = {"Host": SIDECAR_HOST, **(headers or {})}
        connection.request(method, path, body=body.encode("utf-8"), headers=request_headers)
        response = connection.getresponse()
        result = (response.status, {name.lower(): value for name, value in response.getheaders()}, response.read())
        connection.close()
        return result


if __name__ == "__main__":
    unittest.main()
