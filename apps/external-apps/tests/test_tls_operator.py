import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from support import APP_ROOT

sys.path.insert(0, str(APP_ROOT / "deployment"))
from tls_config import certificate_requests, render_hosts
from tls import activate, certbot_command, refresh

DOMAIN = "apps.maverick.example.org"
NAMESPACE = "a" * 12
HOST = "site-" + NAMESPACE + "b" * 20 + "." + DOMAIN


class TlsOperatorTests(unittest.TestCase):
    def projection(self):
        return {"version": 1, "domain": DOMAIN, "expires": 108, "namespaces": [NAMESPACE], "tls_hosts": {NAMESPACE: [HOST]}}

    def test_only_fresh_bounded_names_in_live_namespaces_can_request_acme(self):
        self.assertEqual(certificate_requests(self.projection(), DOMAIN, 100), {"base": [DOMAIN], NAMESPACE: [HOST]})
        for changes in ({"expires": 99}, {"expires": 111}, {"domain": "evil.example.org"}, {"namespaces": []},
                        {"tls_hosts": {NAMESPACE: ["example.org"]}}, {"tls_hosts": {NAMESPACE: ["-d evil.org"]}},
                        {"tls_hosts": {NAMESPACE: [HOST] * 101}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                certificate_requests({**self.projection(), **changes}, DOMAIN, 100)

    def test_acme_is_webroot_http_only_and_does_not_touch_shared_lineages(self):
        command = certbot_command("lineage", {HOST}, Path("/private/tls"), Path("/public/acme"))
        self.assertIn("--webroot", command)
        self.assertNotIn("--nginx", command)
        self.assertNotIn("--dns-standalone", command)
        self.assertIn("/private/tls/config", command)
        self.assertEqual(command[-2:], ["-d", HOST])

    def test_issuance_failure_is_bounded_and_backed_off_even_on_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calls = []
            def fail(*args, **kwargs):
                calls.append(args)
                raise subprocess.CalledProcessError(1, "certbot")
            requests = {"base": [DOMAIN]}
            self.assertEqual(refresh(requests, DOMAIN, root=root, runner=fail)[1], ["base"])
            refresh(requests, DOMAIN, root=root, runner=fail)
            self.assertEqual(len(calls), 1)
            self.assertEqual(len(json.loads((root / "attempts.json").read_text())), 1)

    def test_existing_valid_certificate_is_not_reissued_and_san_expansion_is_batched(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("tls.certificate", return_value=({HOST}, True)):
                with patch("tls.subprocess.run") as runner:
                    refresh({NAMESPACE: [HOST]}, DOMAIN, root=root, runner=runner)
                    runner.assert_not_called()
            other = HOST.replace("site-", "another-")
            with patch("tls.certificate", side_effect=[({HOST}, True), ({HOST, other}, True)]):
                with patch("tls.subprocess.run") as runner:
                    certs, errors = refresh({NAMESPACE: [other]}, DOMAIN, root=root, runner=runner)
                    self.assertFalse(errors)
                    self.assertEqual(certs[0][0], {HOST, other})
                    args = runner.call_args.args[0]
                    self.assertIn(HOST, args)
                    self.assertIn(other, args)
                    self.assertEqual(args.count("-d"), 2)

    def test_failed_nginx_validation_restores_only_owned_config_and_retries_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "hosts.conf").write_text("previous")
            with patch("tls.subprocess.run", side_effect=subprocess.CalledProcessError(1, "nginx")) as runner:
                with self.assertRaises(subprocess.CalledProcessError):
                    activate("replacement", root=root, runner=runner)
                self.assertEqual(runner.call_count, 1)
            self.assertEqual((root / "hosts.conf").read_text(), "previous")
            self.assertTrue((root / "reload.pending").exists())
            with patch("tls.subprocess.run") as runner:
                activate("previous", root=root, runner=runner)
                self.assertEqual(runner.call_args_list[0].args[0], ["/usr/sbin/nginx", "-t"])
                self.assertEqual(runner.call_args_list[1].args[0], ["/usr/bin/systemctl", "reload", "nginx"])
            self.assertFalse((root / "reload.pending").exists())

    def test_renderer_has_only_exact_names_not_a_private_fallback(self):
        rendered = render_hosts([({HOST}, Path("/private/cert"))])
        self.assertIn("server_name " + HOST + ";", rendered)
        self.assertNotIn("default_server", rendered)
        self.assertNotIn("*.", rendered)
