"""Fail-closed tests for managed exact browser-origin certificates."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import tempfile
import unittest

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from core.shared.browser_origin_tls import (
    BrowserOriginTlsError,
    BrowserOriginTlsSettings,
    ensure_browser_origin_tls,
    managed_certificate_paths,
)


class BrowserOriginTlsTestCase(unittest.TestCase):
    domain = "maverick.example.test"
    app_host = "af-111111111111111111111111.sidecars.maverick.example.test"
    other_host = "af-222222222222222222222222.sidecars.maverick.example.test"

    def test_external_wildcard_mode_never_runs_certbot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = self._settings(Path(temp_dir), mode="external_wildcard")
            calls: list[list[str]] = []

            ensure_browser_origin_tls(
                [self.app_host],
                group_key="session:one",
                settings=settings,
                run_command=calls.append,
            )

            self.assertEqual(calls, [])

    def test_managed_mode_rejects_names_outside_reserved_exact_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = self._settings(Path(temp_dir))
            for invalid in (
                "maverick.example.test",
                "*.sidecars.maverick.example.test",
                "af-short.sidecars.maverick.example.test",
                "af-111111111111111111111111.sidecars.attacker.test",
            ):
                with self.subTest(host=invalid), self.assertRaises(BrowserOriginTlsError):
                    ensure_browser_origin_tls(
                        [invalid],
                        group_key="session:one",
                        settings=settings,
                        run_command=lambda _command: self.fail("certbot must not run"),
                    )

    def test_issues_one_san_certificate_and_atomically_publishes_each_host(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = self._settings(root)
            calls: list[list[str]] = []

            def issue(command: list[str]) -> None:
                calls.append(command)
                self._write_lineage(settings, command)

            ensure_browser_origin_tls(
                [self.other_host, self.app_host],
                group_key="session:one",
                settings=settings,
                run_command=issue,
            )

            self.assertEqual(len(calls), 1)
            self.assertEqual(self._domains(calls[0]), [self.app_host, self.other_host])
            self.assertIn("--preferred-challenges", calls[0])
            self.assertIn("http", calls[0])
            for host in (self.app_host, self.other_host):
                certificate_path, private_key_path = managed_certificate_paths(
                    settings.served_root,
                    host,
                )
                certificate = x509.load_pem_x509_certificate(certificate_path.read_bytes())
                names = certificate.extensions.get_extension_for_class(
                    x509.SubjectAlternativeName
                ).value.get_values_for_type(x509.DNSName)
                self.assertEqual(set(names), {self.app_host, self.other_host})
                self.assertEqual(private_key_path.stat().st_mode & 0o777, 0o640)
                self.assertTrue(certificate_path.resolve().parent.is_dir())

    def test_reuses_valid_published_certificate_without_an_acme_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = self._settings(Path(temp_dir))
            ensure_browser_origin_tls(
                [self.app_host],
                group_key="session:one",
                settings=settings,
                run_command=lambda command: self._write_lineage(settings, command),
            )

            ensure_browser_origin_tls(
                [self.app_host],
                group_key="session:one",
                settings=settings,
                run_command=lambda _command: self.fail("valid certificate must be reused"),
            )

    def test_expansion_preserves_existing_sans(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = self._settings(Path(temp_dir))
            ensure_browser_origin_tls(
                [self.app_host],
                group_key="session:one",
                settings=settings,
                run_command=lambda command: self._write_lineage(settings, command),
            )
            calls: list[list[str]] = []

            def expand(command: list[str]) -> None:
                calls.append(command)
                self._write_lineage(settings, command)

            ensure_browser_origin_tls(
                [self.other_host],
                group_key="session:one",
                settings=settings,
                run_command=expand,
            )

            self.assertEqual(len(calls), 1)
            self.assertIn("--expand", calls[0])
            self.assertEqual(self._domains(calls[0]), [self.app_host, self.other_host])

    def test_certbot_failure_does_not_publish_untrusted_material(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = self._settings(Path(temp_dir))

            def fail(_command: list[str]) -> None:
                raise subprocess.CalledProcessError(1, ["certbot"])

            with self.assertRaises(BrowserOriginTlsError):
                ensure_browser_origin_tls(
                    [self.app_host],
                    group_key="session:one",
                    settings=settings,
                    run_command=fail,
                )

            certificate_path, private_key_path = managed_certificate_paths(
                settings.served_root,
                self.app_host,
            )
            self.assertFalse(certificate_path.exists())
            self.assertFalse(private_key_path.exists())

    def _settings(self, root: Path, *, mode: str = "managed_exact") -> BrowserOriginTlsSettings:
        return BrowserOriginTlsSettings(
            mode=mode,
            installation_domain=self.domain,
            tls_root=root / "tls",
            acme_webroot=root / "acme",
            certbot_command="/usr/bin/certbot",
            acme_ca="https://acme.test/directory",
            timeout_seconds=30,
        )

    def _write_lineage(self, settings: BrowserOriginTlsSettings, command: list[str]) -> None:
        cert_name = command[command.index("--cert-name") + 1]
        lineage = settings.certbot_config_root / "live" / cert_name
        lineage.mkdir(parents=True, exist_ok=True)
        self._write_pair(
            lineage / "fullchain.pem",
            lineage / "privkey.pem",
            dns_names=self._domains(command),
        )

    @staticmethod
    def _domains(command: list[str]) -> list[str]:
        return sorted(command[index + 1] for index, value in enumerate(command) if value == "-d")

    @staticmethod
    def _write_pair(
        certificate_path: Path,
        private_key_path: Path,
        *,
        dns_names: list[str],
    ) -> None:
        key = ec.generate_private_key(ec.SECP256R1())
        now = datetime.now(timezone.utc)
        certificate = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, dns_names[0])]))
            .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, dns_names[0])]))
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=90))
            .add_extension(
                x509.SubjectAlternativeName([x509.DNSName(name) for name in dns_names]),
                critical=False,
            )
            .sign(key, hashes.SHA256())
        )
        certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        private_key_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )


if __name__ == "__main__":
    unittest.main()
