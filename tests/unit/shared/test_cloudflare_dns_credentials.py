"""Vault rotation/revocation must also govern unattended Certbot delivery."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("cloudflare_credentials", ROOT / "scripts/deploy/refresh_cloudflare_dns_credentials.py")
credentials = importlib.util.module_from_spec(spec)
spec.loader.exec_module(credentials)


class CloudflareCredentialsTests(unittest.TestCase):
    def test_rotation_replaces_private_projection_and_permissions(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "private", "cloudflare.ini")
            credentials.refresh_credentials(path, resolver=lambda: "a" * 40)
            credentials.refresh_credentials(path, resolver=lambda: "b" * 40)
            self.assertEqual(path.read_text(), "dns_cloudflare_api_token = " + "b" * 40 + "\n")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_failed_resolution_removes_stale_token_and_does_not_report_it(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "cloudflare.ini")
            path.write_text("old token")
            def denied():
                raise RuntimeError("Sensitive dependency error")
            with self.assertRaises(RuntimeError):
                credentials.refresh_credentials(path, resolver=denied)
            self.assertFalse(path.exists())

    def test_symlink_cannot_overwrite_another_file(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder, "target")
            target.write_text("preserve")
            link = Path(folder, "cloudflare.ini")
            link.symlink_to(target)
            with self.assertRaises(ValueError):
                credentials.refresh_credentials(link, resolver=lambda: "a" * 40)
            self.assertEqual(target.read_text(), "preserve")

    def test_ini_injection_is_rejected_without_leaving_a_credential(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "cloudflare.ini")
            with self.assertRaises(ValueError):
                credentials.refresh_credentials(path, resolver=lambda: "a" * 40 + "\nother = injected")
            self.assertFalse(path.exists())

    def test_cli_hides_exception_values(self):
        with tempfile.TemporaryDirectory() as folder:
            env = Path(folder, "installation.env")
            env.write_text("")
            output = io.StringIO()
            with patch.object(credentials.os, "geteuid", return_value=0), patch.object(credentials, "refresh_credentials", side_effect=RuntimeError("secret-token-value")), contextlib.redirect_stdout(output):
                result = credentials.main(["--env-file", str(env)])
            self.assertEqual(result, 1)
            self.assertEqual(json.loads(output.getvalue()), {"status": "blocked", "error_type": "RuntimeError"})

    def test_paginated_dns_inspection_is_read_only_and_ignores_api_timestamps(self):
        records = [{"name": "example.test", "type": "MX", "content": "mx.example.test", "proxied": False}]
        def getter(token, endpoint):
            self.assertEqual(token, "a" * 40)
            if "/dns_records?" not in endpoint:
                return {"result": {"name": "example.test", "status": "active", "name_servers": ["one", "two"]}}
            if endpoint.endswith("&page=1"):
                return {"result": records, "result_info": {"total_pages": 2}}
            return {"result": [], "result_info": {"total_pages": 2}}
        result = credentials.inspect_zone("a" * 32, resolver=lambda: "a" * 40, getter=getter)
        records[0]["modified_on"] = "later"
        again = credentials.inspect_zone("a" * 32, resolver=lambda: "a" * 40, getter=getter)
        self.assertEqual(result["records_sha256"], again["records_sha256"])
        self.assertEqual(result["record_count"], 1)
        self.assertNotIn("content", result["records"][0])


if __name__ == "__main__":
    unittest.main()
