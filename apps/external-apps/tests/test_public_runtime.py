"""Public routing, cache/revocation and tenant isolation with synthetic bundles."""
from pathlib import Path
import tempfile
import time
import unittest

from support import apply_args, approve, prepare, service
from external_apps.deployment import load
from external_apps.files import atomic_write, encoded
from public_server.serving import PublicRuntime


class PublicRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.a = service(self.base / "tenant-a")
        self.b = service(self.base / "tenant-b", workspace="tenant-b")
        mounts = {load(s.root)["namespace"]: s.root / "public" for s in (self.a, self.b)}
        self.authority = self.base / "mounts.json"
        atomic_write(self.authority, encoded({"version": 1, "domain": "apps.example.test", "expires": time.time() + 8, "namespaces": list(mounts)}))
        self.runtime = PublicRuntime(domain="apps.example.test", mounts=mounts, projection=self.authority)
        self.plan = approve(self.a, prepare(self.a))
        self.a.handle(apply_args(self.plan))
        self.host = self.plan["hostname"]

    def test_headers_head_and_revoked_304(self):
        code, headers, data = self.runtime.response("GET", self.host, "/")
        self.assertEqual(code, 200)
        self.assertIn(b"one", data)
        self.assertEqual(headers["X-External-Release"], self.plan["release_id"])
        self.assertNotIn("Set-Cookie", headers)
        self.assertIn("worker-src 'none'", headers["Content-Security-Policy"])
        self.assertEqual(self.runtime.response("HEAD", self.host, "/")[2], b"")
        self.assertEqual(self.runtime.response("GET", self.host, "/", {"if-none-match": headers["ETag"]})[0], 304)
        self.a.handle({"action": "suspend", "external_app_id": self.plan["app_id"], "confirm": True, "expected_generation": 1, "idempotency_key": "revoke-cached-site"})
        self.assertEqual(self.runtime.response("GET", self.host, "/", {"if-none-match": headers["ETag"]})[0], 503)
        self.assertEqual(self.runtime.response("GET", self.host, f"/_releases/{self.plan['release_id']}/main.js")[0], 503)

    def test_expired_projection_and_unknown_host_fail_closed(self):
        atomic_write(self.authority, encoded({"version": 1, "domain": "apps.example.test", "expires": time.time() - 1, "namespaces": list(self.runtime.mounts)}))
        self.assertEqual(self.runtime.response("GET", self.host, "/")[0], 503)
        self.assertEqual(self.runtime.response("GET", "private.example.test", "/api/status")[0], 404)

    def test_old_assets_survive_switch_but_cross_app_release_is_denied(self):
        second = approve(self.a, prepare(self.a, app_id=self.plan["app_id"], content="two"))
        self.a.handle(apply_args(second, "publish-second-release"))
        self.assertIn(b'one', self.runtime.response("GET", self.host, f"/_releases/{self.plan['release_id']}/main.js")[2])
        b_plan = approve(self.b, prepare(self.b, content="other-workspace"))
        self.b.handle(apply_args(b_plan))
        self.assertEqual(self.runtime.response("GET", self.host, f"/_releases/{b_plan['release_id']}/main.js")[0], 404)

    def test_spa_fallback_not_for_assets_private_routes_or_non_navigation(self):
        spa = approve(self.a, prepare(self.a, app_id=self.plan["app_id"], content="spa", format_="spa_bundle"))
        self.a.handle(apply_args(spa, "publish-spa-release"))
        self.assertEqual(self.runtime.response("GET", self.host, "/route", {"accept": "text/html"})[0], 200)
        for path in ("/missing.js", "/api/status", "/app/chat", "/.git/config", "/.well-known/session", "/%2e%2e/private", "/a%2fb"):
            self.assertGreaterEqual(self.runtime.response("GET", self.host, path, {"accept": "text/html"})[0], 400)
        self.assertEqual(self.runtime.response("GET", self.host, "/route", {"accept": "application/json"})[0], 404)
        self.assertEqual(self.runtime.response("POST", self.host, "/")[0], 405)

    def test_warm_cache_cannot_mask_changed_file(self):
        self.assertEqual(self.runtime.response("GET", self.host, "/")[0], 200)
        path = self.a.root / "public/artifacts" / self.plan["release"]["digest"] / "files/index.html"
        path.write_text("tampered")
        self.assertEqual(self.runtime.response("GET", self.host, "/")[0], 503)


if __name__ == "__main__":
    unittest.main()
