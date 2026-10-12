"""Installation plans must be scoped, immutable, idempotent and reversible."""

from pathlib import Path
import tempfile
import unittest

from core.installation.errors import InstallationError
from core.installation.service import InstallationService
from core.installation.validation import hostname, public_ip


class FakeDns:
    def __init__(self, *args, **kwargs):
        pass

    def zone(self, host):
        return {"id": "a" * 32, "name": "example.com", "status": "active", "name_servers": ["one", "two"]}

    def records(self, zone):
        return [{"id": "b" * 32, "name": "*.example.com", "type": "A", "content": "8.8.8.8", "proxied": False}]


class InstallationServiceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.service = InstallationService(Path(self.folder.name), environment={}, dns_factory=FakeDns)

    def tearDown(self):
        self.folder.cleanup()

    def plan(self, **overrides):
        return self.service.plan(address="https://maverick.example.com/", target_ip="8.8.8.8", **overrides)

    def test_hostname_and_address_validation_rejects_shell_or_private_targets(self):
        self.assertEqual(hostname("https://Maverick.example.com/"), "maverick.example.com")
        for value in ("https://user:password@example.com", "localhost", "example.com/other", "example.com;touch", "example.com\n"):
            with self.subTest(value=value), self.assertRaises(InstallationError):
                hostname(value)
        for value in ("127.0.0.1", "10.0.0.1", "::1", "not-an-ip"):
            with self.subTest(value=value), self.assertRaises(InstallationError):
                public_ip(value)

    def test_plan_preserves_matching_existing_wildcard_and_has_required_tls_sans(self):
        plan = self.plan()
        self.assertEqual([item["action"] for item in plan["dns_changes"]], ["keep", "keep"])
        self.assertEqual(plan["certificate_names"], ["maverick.example.com", "*.sidecars.maverick.example.com"])
        self.assertNotIn("raw_value", str(plan))

    def test_apply_is_idempotent_and_conflicting_changes_are_rejected(self):
        plan = self.plan()
        first = self.service.apply(plan["plan_id"], actor_user_id="admin")
        again = self.service.apply(plan["plan_id"], actor_user_id="admin")
        self.assertEqual(first["job_id"], again["job_id"])
        other = self.plan()
        with self.assertRaisesRegex(InstallationError, "installation_change_in_progress"):
            self.service.apply(other["plan_id"])

    def test_changed_plan_content_and_stale_generation_are_rejected(self):
        plan = self.plan()
        modified = {**plan, "target_ip": "1.1.1.1"}
        self.service.store.write("plans", modified, plan["plan_id"])
        with self.assertRaisesRegex(InstallationError, "plan_integrity_failed"):
            self.service.apply(plan["plan_id"])
        self.service.store.write("plans", plan, plan["plan_id"])
        self.service.store.write("configuration", {**self.service.configuration(), "generation": 1})
        with self.assertRaisesRegex(InstallationError, "stale_installation_plan"):
            self.service.apply(plan["plan_id"])

    def test_manual_plan_is_actionable_but_cannot_claim_automatic_renewal(self):
        plan = self.plan(dns_provider="manual")
        self.assertEqual(plan["blocking_issues"][0]["code"], "dns_automation_connection_required")
        self.assertEqual(len(plan["dns_changes"]), 2)
        with self.assertRaisesRegex(InstallationError, "dns_automation_connection_required"):
            self.service.apply(plan["plan_id"])

    def test_rollback_cannot_overwrite_a_later_installation_generation(self):
        plan = self.plan()
        job = self.service.apply(plan["plan_id"])
        job["status"] = "failed"
        self.service.store.write("jobs", job, job["job_id"])
        self.service.store.write("configuration", {**self.service.configuration(), "generation": 2})
        with self.assertRaisesRegex(InstallationError, "stale_installation_rollback"):
            self.service.rollback(job["job_id"])
