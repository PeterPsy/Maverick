"""Production TLS maintenance must honor CA cooldowns and validate before activation."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.deploy import maintain_browser_origin_wildcard as maintenance


class WildcardMaintenanceTests(unittest.TestCase):
    def setUp(self):
        validator = patch.object(maintenance, "validate_certbot_executable")
        self.validate_certbot = validator.start()
        self.addCleanup(validator.stop)

    def test_retry_window_prevents_secret_delivery_and_any_certbot_request(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder)
            retry = datetime.now(timezone.utc) + timedelta(hours=2)
            error = subprocess.CalledProcessError(1, ["certbot"], stderr="retry after " + retry.strftime("%Y-%m-%d %H:%M:%S") + " UTC")
            maintenance.record_issuance_failure(state, "example.test", maintenance.CA, error)
            with patch.object(maintenance, "refresh_credentials") as delivery:
                result = maintenance.maintain("example.test", "admin@example.test", Path("/nginx.conf"), state,
                                              runner=lambda *args, **kwargs: self.fail("Unexpected CA request"))
            delivery.assert_not_called()
            self.validate_certbot.assert_not_called()
            self.assertEqual(result["status"], "waiting")

    def test_failed_certificate_never_activates_and_persists_retry_without_error_values(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(maintenance, "refresh_credentials"):
            calls = []
            def runner(command, **kwargs):
                calls.append(command)
                return subprocess.CompletedProcess(command, 1, "", "Sensitive dependency error")
            result = maintenance.maintain("example.test", "admin@example.test", Path("/nginx.conf"), Path(folder), runner=runner)
            self.assertEqual(len(calls), 1)
            self.assertEqual(result["status"], "issuance_failed")
            self.assertNotIn("Sensitive", str(result))
            self.validate_certbot.assert_called_once_with(maintenance.ROOT)

    def test_first_activation_requires_real_renewal_dry_run_and_creates_restart_marker(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(maintenance, "refresh_credentials"), patch.object(maintenance, "verify_wildcard_https") as https:
            calls = []
            def runner(command, **kwargs):
                calls.append(command)
                output = '{"certificate":"/verified/fullchain.pem", "backend_restart_required":true}' if len(calls) == 3 else ""
                return subprocess.CompletedProcess(command, 0, output, "")
            state = Path(folder)
            result = maintenance.maintain("example.test", "admin@example.test", Path("/nginx.conf"), state, runner=runner)
            self.assertIn("*.sidecars.example.test", calls[0])
            for command in calls[:2]:
                self.assertEqual(command[0], str(maintenance.ROOT / "scripts/deploy/loopino-certbot"))
                for flag, name in (("--config-dir", "config"), ("--work-dir", "work"), ("--logs-dir", "logs")):
                    self.assertEqual(command[command.index(flag) + 1], str(maintenance.ROOT / "installation/tls/certbot" / name))
            self.assertIn("--dry-run", calls[1])
            self.assertIn("--apply", calls[2])
            self.assertTrue((state / "restart-required").exists())
            self.assertTrue(result["renewal_verified"])
            https.assert_called_once_with("example.test")
            self.validate_certbot.assert_called_once_with(maintenance.ROOT)

    def test_untrusted_live_https_is_not_active_and_retains_restart_intent(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(maintenance, "refresh_credentials"), patch.object(maintenance, "verify_wildcard_https", side_effect=OSError("Untrusted TLS")):
            state = Path(folder)
            (state / "renewal-verified-example.test").touch()
            calls = []
            def runner(command, **kwargs):
                calls.append(command)
                output = '{"certificate":"/verified/fullchain.pem", "backend_restart_required":true}' if len(calls) == 2 else ""
                return subprocess.CompletedProcess(command, 0, output, "")
            result = maintenance.maintain("example.test", "admin@example.test", Path("/nginx.conf"), state, runner=runner)
            self.assertEqual(result["status"], "wildcard_https_verification_failed")
            self.assertTrue((state / "restart-required").exists())
            self.validate_certbot.assert_called_once_with(maintenance.ROOT)

    def test_failed_dry_run_preserves_current_routing(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(maintenance, "refresh_credentials"):
            calls = []
            def runner(command, **kwargs):
                calls.append(command)
                return subprocess.CompletedProcess(command, 0 if len(calls) == 1 else 1, "", "")
            state = Path(folder)
            result = maintenance.maintain("example.test", "admin@example.test", Path("/nginx.conf"), state, runner=runner)
            self.assertEqual(result["status"], "renewal_verification_failed")
            self.assertEqual(len(calls), 2)
            self.assertFalse((state / "restart-required").exists())
            self.validate_certbot.assert_called_once_with(maintenance.ROOT)

    def test_changed_hostname_requires_its_own_renewal_verification(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(maintenance, "refresh_credentials"):
            state = Path(folder)
            (state / "renewal-verified-old.example.test").touch()
            calls = []
            def runner(command, **kwargs):
                calls.append(command)
                return subprocess.CompletedProcess(command, 0 if len(calls) == 1 else 1, "", "")
            result = maintenance.maintain("new.example.test", "admin@example.test", Path("/nginx.conf"), state, runner=runner)
            self.assertEqual(result["status"], "renewal_verification_failed")
            self.assertIn("--dry-run", calls[1])
            self.validate_certbot.assert_called_once_with(maintenance.ROOT)


if __name__ == "__main__":
    unittest.main()
