import tempfile
import unittest
from pathlib import Path

from support import apply_args, approve, prepare, service
from external_apps.deployment import configure, load, public_domain
from external_apps.errors import AppError
from external_apps.tls_requests import requested_hosts


class InstallationDomainTests(unittest.TestCase):
    def test_domain_follows_any_installation_not_a_provider_or_fixed_hostname(self):
        for installation in ("maverick.loopino.ai", "example.org", "tenant.tools.example.net"):
            self.assertEqual(public_domain(installation), "apps." + installation)
        self.assertEqual(public_domain("MAVERICK.EXAMPLE.ORG"), "apps.maverick.example.org")
        for invalid in ("", "localhost", "34.17.71.112", "https://maverick.example.org", "*.example.org", "example.org:443", "example.org/path"):
            with self.subTest(invalid=invalid), self.assertRaises(AppError):
                public_domain(invalid)

    def test_domain_change_is_explicit_and_blocked_for_nonempty_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = configure(root, "example.org", has_apps=False)
            updated = configure(root, "maverick.example.net", has_apps=False)
            self.assertEqual(first["namespace"], updated["namespace"])
            self.assertEqual(load(root)["installation_domain"], "maverick.example.net")
            with self.assertRaisesRegex(AppError, "domain_change_not_supported"):
                configure(root, "other.example.net", has_apps=True)

    def test_pending_tls_does_not_consume_approved_plan_or_change_public_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            app = service(Path(directory))
            plan = approve(app, prepare(app))
            def pending(_host):
                raise AppError("public_tls_not_ready", 503)
            app.preflight = pending
            with self.assertRaisesRegex(AppError, "public_tls_not_ready"):
                app.handle(apply_args(plan))
            self.assertEqual(app.store.get("plans", plan["id"])["status"], "ready")
            self.assertEqual(app.handle({"action": "get", "external_app_id": plan["app_id"]})["app"]["binding"]["generation"], 0)
            app.preflight = lambda _host: None
            self.assertEqual(app.handle(apply_args(plan))["status"], "published")
            app.preflight = pending
            self.assertEqual(app.handle(apply_args(plan))["status"], "published")

    def test_only_ready_catalog_names_request_tls_and_archive_revokes_intent(self):
        with tempfile.TemporaryDirectory() as directory:
            app = service(Path(directory))
            config = load(app.root)
            requested = lambda: requested_hosts(app.store, config["namespace"], config["domain"])
            self.assertEqual(requested(), [])
            plan = prepare(app)
            self.assertEqual(requested(), [plan["hostname"]])
            app.handle({"action": "archive", "external_app_id": plan["app_id"], "expected_generation": 0,
                        "confirm": True, "idempotency_key": "archive-for-tls"})
            self.assertEqual(requested(), [])
