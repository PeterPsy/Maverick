"""Host jobs must survive waits/restarts and verify the destination before committing."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.installation.service import InstallationService
from core.installation.worker import InstallationWorker
from tests.unit.installation.test_service import FakeDns


class InstallationWorkerTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.service = InstallationService(Path(self.folder.name), environment={}, dns_factory=FakeDns)
        self.service.store.write("configuration", {**self.service.configuration(), "installation_id": "a" * 32})
        self.plan = self.service.plan(address="maverick.example.com", target_ip="8.8.8.8")
        self.job = self.service.apply(self.plan["plan_id"])
        self.commits = []

    def tearDown(self):
        self.folder.cleanup()

    def worker(self, **overrides):
        values = dict(propagation=lambda *args: True, dns=lambda *args: {"waiting": False},
            certificates=lambda *args: {"waiting": False, "certificates": {}, "renewal_verified": True},
            stage=lambda *args: {}, commit=lambda *args: self.commits.append(True),
            probe=lambda *args: {"proof": {"nonce": self.job["probe_nonce"], "hostname": self.plan["hostname"]}},
            verify=lambda *args: {"healthy": True, "checks": []})
        values.update(overrides)
        return InstallationWorker(self.service, **values)

    def test_ca_wait_is_durable_and_does_not_commit_the_address(self):
        result = self.worker(certificates=lambda *args: {"waiting": True, "retry_at": "2099-01-01T00:00:00+00:00"}).advance(self.job)
        self.assertEqual(result["status"], "waiting_ca")
        self.assertFalse(self.commits)
        with patch("core.installation.worker.discover_public_ip", return_value="8.8.8.8"):
            resumed = self.worker(dns=lambda *args: self.fail("Must honor CA cooldown")).tick()
        self.assertEqual(resumed["status"], "waiting_ca")

    def test_wrong_server_never_commits_or_changes_the_generation(self):
        with self.assertRaisesRegex(ValueError, "wrong_server_at_target_address"):
            self.worker(probe=lambda *args: {"proof": {"nonce": "different"}}).advance(self.job)
        self.assertFalse(self.commits)
        self.assertEqual(self.service.configuration()["generation"], 0)

    def test_activation_is_only_ready_after_backend_restart_and_live_checks(self):
        worker = self.worker()
        pending = worker.advance(self.job)
        self.assertEqual(pending["step"], "restarting")
        self.assertEqual(pending["status"], "verifying")
        self.assertTrue((self.service.store.root / "private/restart-required").exists())
        ready = self.worker().advance(pending)
        self.assertEqual(ready["status"], "ready")
        self.assertEqual(len(self.commits), 1)

    def test_temporary_backend_restart_outage_is_a_waiting_state(self):
        pending = self.worker().advance(self.job)
        def unavailable(*args):
            raise OSError("connection temporarily unavailable")
        result = self.worker(probe=unavailable).advance(pending)
        self.assertEqual(result["status"], "verifying")
        self.assertEqual(result["step"], "restarting")
