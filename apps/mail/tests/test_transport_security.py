"""Transport security and UID-scoped deletion regressions."""

from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from providers import imap_smtp
from connections import _security


class TransportSecurityTest(unittest.TestCase):
    def test_ssl_and_starttls_always_verify_certificates_and_hostnames(self):
        settings = {"imap_host": "mail.example", "imap_port": 993, "smtp_host": "mail.example", "smtp_port": 465}
        for protocol, opener in [("imap", imap_smtp._open_imap), ("smtp", imap_smtp._open_smtp)]:
            for security in ("ssl", "starttls"):
                with self.subTest(protocol=protocol, security=security), patch.object(imap_smtp.imaplib, "IMAP4_SSL") as imap_ssl, patch.object(imap_smtp.imaplib, "IMAP4") as imap_plain, patch.object(imap_smtp.smtplib, "SMTP_SSL") as smtp_ssl, patch.object(imap_smtp.smtplib, "SMTP") as smtp_plain:
                    opener({**settings, f"{protocol}_security": security})
                    factory = (imap_ssl if protocol == "imap" else smtp_ssl) if security == "ssl" else (imap_plain if protocol == "imap" else smtp_plain)
                    kwargs = factory.call_args.kwargs if security == "ssl" else factory.return_value.starttls.call_args.kwargs
                    context = kwargs["ssl_context" if protocol == "imap" else "context"]
                    self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
                    self.assertTrue(context.check_hostname)

    def test_cleartext_is_rejected_before_opening_a_socket(self):
        for protocol, opener in [("imap", imap_smtp._open_imap), ("smtp", imap_smtp._open_smtp)]:
            with self.subTest(protocol=protocol):
                with self.assertRaises(ValueError):
                    _security("none", protocol)
                with self.assertRaisesRegex(ValueError, "requires verified TLS"):
                    opener({f"{protocol}_host": "localhost", f"{protocol}_port": 1, f"{protocol}_security": "none"})

    def test_real_ssl_handshakes_reject_untrusted_and_wrong_hostname_certificates(self):
        with tempfile.TemporaryDirectory() as tmp:
            cert, key = Path(tmp) / "cert.pem", Path(tmp) / "key.pem"
            subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost", "-keyout", str(key), "-out", str(cert)], check=True, capture_output=True)
            server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            server_context.load_cert_chain(cert, key)
            for protocol, opener in [("imap", imap_smtp._open_imap), ("smtp", imap_smtp._open_smtp)]:
                for trust_cert in (False, True):
                    with self.subTest(protocol=protocol, trust_cert=trust_cert), socket.socket() as listener:
                        listener.bind(("127.0.0.1", 0))
                        listener.listen()
                        listener.settimeout(3)
                        def serve():
                            with listener.accept()[0] as client:
                                try:
                                    with server_context.wrap_socket(client, server_side=True):
                                        pass
                                except ssl.SSLError:
                                    pass
                        worker = threading.Thread(target=serve)
                        worker.start()
                        context = ssl.create_default_context(cafile=str(cert)) if trust_cert else ssl.create_default_context()
                        try:
                            with patch.object(imap_smtp.ssl, "create_default_context", return_value=context), self.assertRaises(ssl.SSLCertVerificationError):
                                opener({f"{protocol}_host": "127.0.0.1", f"{protocol}_port": listener.getsockname()[1]})
                        finally:
                            worker.join(4)
                        self.assertFalse(worker.is_alive())

    def test_fallback_expunge_only_removes_requested_uid(self):
        deleted = {99}
        client = Mock(capabilities=(b"UIDPLUS",))
        client.select.return_value = ("OK", [])
        def uid(command, value, *args):
            if command == "MOVE":
                return "NO", []
            if command == "STORE":
                deleted.add(int(value))
            if command == "EXPUNGE":
                deleted.discard(int(value))
            return "OK", []
        client.uid.side_effect = uid
        imap_smtp._move_message(client, "INBOX", 7, "Trash")
        self.assertEqual(deleted, {99})
        client.expunge.assert_not_called()
        client.uid.assert_any_call("EXPUNGE", "7")

    def test_unsupported_safe_move_does_not_copy_or_delete(self):
        client = Mock(capabilities=())
        client.select.return_value = ("OK", [])
        client.uid.return_value = ("NO", [])
        with self.assertRaisesRegex(ValueError, "MOVE or UIDPLUS"):
            imap_smtp._move_message(client, "INBOX", 7, "Trash")
        self.assertEqual(client.uid.call_count, 1)
        client.expunge.assert_not_called()
