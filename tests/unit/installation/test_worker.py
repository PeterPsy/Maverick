"""Host jobs must survive waits/restarts and verify the destination before committing."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.installation.service import InstallationService, timestamp
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
        values = dict(delegation=lambda *args: {"waiting": False}, propagation=lambda *args: True, dns=lambda *args: {"waiting": False},
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

    def test_a_new_host_refreshes_restored_public_ip_without_repeated_discovery(self):
        self.service.store.write('worker', {'host_boot': 'previous-host',
            'public_ip': '8.8.8.8', 'public_ip_checked_at': timestamp()})
        worker = self.worker(certificates=lambda *args: {'waiting': True})
        with patch('core.installation.worker.discover_public_ip', return_value='1.1.1.1') as discover:
            worker.tick()
            self.assertEqual(self.service.store.read('worker')['public_ip'], '1.1.1.1')
            worker.tick()
            discover.assert_called_once()

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

    def test_activation_recovers_after_environment_write_without_double_generation(self):
        original = self.service.store.write
        fail = [True]
        def crash(kind, value, key='current'):
            if kind == 'configuration' and fail[0]:
                fail[0] = False
                raise OSError('Simulated publication interruption')
            return original(kind, value, key)
        with patch.object(self.service.store, 'write', side_effect=crash):
            with self.assertRaises(OSError):
                self.worker().advance(self.job)
        resumed = self.worker().advance(self.service.status(self.job['job_id'])['job'])
        self.assertEqual(resumed['activated_generation'], 1)
        self.assertEqual(self.service.configuration()['generation'], 1)
        self.assertEqual(resumed['step'], 'restarting')

    def test_rollback_recovery_verifies_after_restart(self):
        self.worker().advance(self.job)
        rollback = self.service.rollback(self.job['job_id'])
        original = self.service.store.write
        fail = [True]
        def crash(kind, value, key='current'):
            if kind == 'jobs' and value.get('step') == 'rollback_restarting' and fail[0]:
                fail[0] = False
                raise OSError('Simulated rollback publication interruption')
            return original(kind, value, key)
        worker = self.worker(restore=lambda *a: None, dns_restore=lambda *a: None)
        with patch.object(self.service.store, 'write', side_effect=crash):
            with self.assertRaises(OSError):
                worker.rollback(rollback)
        resumed = worker.rollback(self.service.status(rollback['job_id'])['job'])
        self.assertEqual(self.service.configuration()['generation'], 2)
        self.assertEqual(resumed['status'], 'rolling_back')
        (self.service.store.root / 'private/restart-required').unlink()
        self.assertEqual(worker.rollback(resumed)['status'], 'rolled_back')

    def test_destination_and_certificates_are_ready_before_public_dns_moves(self):
        calls = []
        worker = self.worker(
            certificates=lambda *a: (calls.append('certificates') or {'waiting': False, 'certificates': {}}),
            stage=lambda *a: calls.append('nginx'),
            probe=lambda *a: (calls.append('proof') or {'proof': {'nonce': self.job['probe_nonce']}}),
            dns=lambda *a: (calls.append('dns') or {'waiting': False}),
            commit=lambda *a: calls.append('commit'))
        worker.advance(self.job)
        self.assertEqual(calls, ['certificates', 'nginx', 'proof', 'dns', 'commit'])

    def test_ca_wait_and_wrong_destination_never_move_public_dns(self):
        dns = lambda *args: self.fail('Public traffic must stay on the old server')
        waiting = self.worker(dns=dns, certificates=lambda *a: {'waiting': True}).advance(self.job)
        self.assertEqual(waiting['status'], 'waiting_ca')
        with self.assertRaisesRegex(ValueError, 'wrong_server_at_target_address'):
            self.worker(dns=dns, probe=lambda *a: {'proof': {'nonce': 'wrong'}}).advance(self.job)
