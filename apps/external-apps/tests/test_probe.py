"""Public DNS only, exact release bytes and no credential forwarding."""
import hashlib
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from external_apps.errors import AppError
from external_apps.probe import verify_https


class ProbeTests(unittest.TestCase):
    def test_private_and_mixed_dns_are_rejected_before_connect(self):
        for ips in (["127.0.0.1"], ["::1"], ["8.8.8.8", "10.0.0.1"]):
            addresses = [(None, None, None, None, (ip, 443)) for ip in ips]
            with patch("external_apps.probe.socket.getaddrinfo", return_value=addresses), patch("external_apps.probe.http.client.HTTPSConnection") as connect:
                with self.assertRaisesRegex(AppError, "address_denied"):
                    verify_https("demo.example.test", {"release_id": "release"}, "hash")
                connect.assert_not_called()

    def test_exact_response_required_without_redirect_or_cookies(self):
        content = b"<!doctype html><h1>Proof</h1>"
        for status, release, data, expected in ((200, "release", content, True), (302, "release", content, False), (200, "wrong", content, False), (200, "release", b"wrong", False)):
            with self.subTest(status=status, release=release, data=data):
                connection = MagicMock()
                response = connection.getresponse.return_value
                response.status = status
                response.getheader.return_value = release
                response.read.return_value = data
                with patch("external_apps.probe.socket.getaddrinfo", return_value=[(None, None, None, None, ("8.8.8.8", 443))]), patch("external_apps.probe.http.client.HTTPSConnection", return_value=connection):
                    if expected:
                        result = verify_https("demo.example.test", {"release_id": "release"}, hashlib.sha256(content).hexdigest())
                        self.assertEqual(result["status"], "healthy")
                    else:
                        with self.assertRaises(AppError):
                            verify_https("demo.example.test", {"release_id": "release"}, hashlib.sha256(content).hexdigest())
                connection.close.assert_called_once()
                headers = connection.request.call_args.kwargs["headers"]
                self.assertNotIn("Cookie", headers)
                self.assertNotIn("Authorization", headers)


if __name__ == "__main__":
    unittest.main()
