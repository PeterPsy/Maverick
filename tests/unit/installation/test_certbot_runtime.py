"""One protected isolated Certbot and rooted DNS issuance/renewal commands."""

import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.installation.certificates import prepare_certificates
from core.shared.installation_material import certbot_executable, certbot_preflight, validate_certbot_executable
from core.shared.installer import preflight_check
from tests.unit.shared.test_installer_systemd import _make_config


class CertbotRuntimeTests(unittest.TestCase):
    def test_native_issuance_and_renewal_use_identical_isolated_binary_and_directories(self):
        root = Path(__file__).resolve().parents[3]
        service = SimpleNamespace(store=SimpleNamespace(repository_root=root))
        calls = []
        with tempfile.TemporaryDirectory() as folder, \
             patch("core.installation.certificates.validate_certbot_executable"), \
             patch("core.installation.certificates.refresh_credentials"):
            result = prepare_certificates(service, {"job_id":"a"*32,"actor_user_id":"actor"},
                {"hostname":"loopino.example.com","dns_secret_ref":"platform:secret-alias/cloudflare-token"},
                Path(folder), runner=lambda command, **kwargs: calls.append(command) or SimpleNamespace(returncode=0))
        self.assertTrue(result["renewal_verified"])
        self.assertEqual(len(calls),4)
        for command in calls:
            self.assertEqual(command[0],str(root / "scripts/deploy/loopino-certbot"))
            for flag, leaf in (("--config-dir","config"),("--work-dir","work"),("--logs-dir","logs")):
                self.assertEqual(command[command.index(flag)+1],str(root / "installation/tls/certbot" / leaf))
            self.assertIn("--dns-cloudflare",command)

    def test_preflight_requires_cloudflare_plugin_without_global_path_fallback(self):
        root = Path(__file__).resolve().parents[3]
        with patch("core.shared.installation_material.validate_certbot_executable"), \
             patch("core.shared.installation_material.subprocess.run",return_value=SimpleNamespace(returncode=0,stdout="* standalone")) as run:
            with self.assertRaisesRegex(ValueError,"dns-cloudflare"):
                certbot_preflight(root)
            self.assertEqual(run.call_args.args[0][0],str(certbot_executable(root)))
        with patch("core.shared.installer.certbot_preflight",side_effect=ValueError("dns-cloudflare missing")):
            report=preflight_check(_make_config(root),live_apply=False,request_tls=True)
            self.assertTrue(any("dns-cloudflare missing" in error for error in report.errors))

    @unittest.skipUnless(os.geteuid()==0,"protected installation executable contract requires root ownership")
    def test_symlinks_writable_files_and_untrusted_ancestor_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=certbot_executable(root)
            path.parent.mkdir(parents=True);path.write_text("#!/bin/sh\nexit 0\n");path.chmod(0o755)
            vendor=root / ".venv/bin/certbot"
            vendor.parent.mkdir(parents=True);vendor.write_text("#!/bin/sh\nexit 0\n");vendor.chmod(0o755)
            (path.parent / "isolated_certbot.py").write_text("# protected launcher implementation\n")
            validate_certbot_executable(root)
            path.chmod(0o775)
            with self.assertRaisesRegex(ValueError,"protected"):
                validate_certbot_executable(root)
            path.chmod(0o755);path.parent.chmod(0o777)
            with self.assertRaisesRegex(ValueError,"protected"):
                validate_certbot_executable(root)
            path.parent.chmod(0o755);path.unlink();path.symlink_to("/usr/bin/true")
            with self.assertRaisesRegex(ValueError,"protected"):
                validate_certbot_executable(root)
