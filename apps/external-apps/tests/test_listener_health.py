"""Readiness and peer disconnects must not create an error-log loop."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from support import APP_ROOT  # Establish the app import roots.
from public_server.server import PublicServer
from scripts.external_apps_supervisor import listener_healthy


class ListenerHealthTests(unittest.TestCase):
    def test_readiness_requests_head_without_a_body(self):
        self.assertTrue(APP_ROOT.is_dir())
        with patch("socket.socket") as factory:
            sock = factory.return_value.__enter__.return_value
            sock.recv.return_value = b"HTTP/1.0 404 Not Found\r\n"
            self.assertTrue(listener_healthy(Path("/unused.sock")))
            sock.sendall.assert_called_once_with(b"HEAD / HTTP/1.0\r\nHost: invalid\r\n\r\n")
            sock.recv.return_value = b"HTTP/1.0 200 OK\r\n"
            self.assertFalse(listener_healthy(Path("/unused.sock")))

    def test_missing_listener_is_not_ready(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertFalse(listener_healthy(Path(root) / "missing.sock"))

    def test_only_expected_peer_disconnects_are_silent(self):
        server = object.__new__(PublicServer)
        with patch("socketserver.UnixStreamServer.handle_error") as report:
            for error in (BrokenPipeError(), ConnectionResetError(), TimeoutError()):
                try:
                    raise error
                except Exception:
                    server.handle_error(None, None)
            report.assert_not_called()
            try:
                raise ValueError("unexpected runtime defect")
            except ValueError:
                server.handle_error(None, None)
            report.assert_called_once_with(None, None)


if __name__ == "__main__":
    unittest.main()
