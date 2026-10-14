"""Fail-closed tests for managed exact browser-origin certificates."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import tempfile
import unittest

from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from core.shared.browser_origin_tls_backoff import issuance_retry_at, record_issuance_failure

from core.shared.browser_origin_tls import (
    BrowserOriginTlsError,
    BrowserOriginTlsSettings,
    ensure_browser_origin_tls,
    managed_certificate_paths,
)


class BrowserOriginTlsTestCase(unittest.TestCase):
    domain = "loopino.example.test"
    app_host = "af-111111111111111111111111.sidecars.loopino.example.test"
    other_host = "af-222222222222222222222222.sidecars.loopino.example.test"

    def test_service_user_managed_exact_is_denied_before_any_write_or_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as folder, patch("core.shared.browser_origin_tls.os.geteuid", return_value=1234):
            settings = self._settings(Path(folder))
            with self.assertRaisesRegex(BrowserOriginTlsError, "managed_exact_operator_required"):
                ensure_browser_origin_tls([self.app_host], group_key="session:one", settings=settings,
                                          run_command=lambda _: self.fail("must not invoke issuer"))
            self.assertFalse(settings.tls_root.exists())

    def test_service_user_external_wildcard_needs_no_issuer(self) -> None:
        with tempfile.TemporaryDirectory() as folder, patch("core.shared.browser_origin_tls.os.geteuid", return_value=1234):
            ensure_browser_origin_tls([self.app_host], group_key="session:one",
                settings=self._settings(Path(folder), mode="external_wildcard"),
                run_command=lambda _: self.fail("wildcard must not invoke issuer"))

    def test_installer_reports_unsupported_service_user_managed_exact(self) -> None:
        from dataclasses import replace
        from core.shared.installer import preflight_check
        from tests.unit.shared.test_installer_systemd import _make_config
        root = Path(__file__).resolve().parents[3]
        config = replace(_make_config(root), service_user="loopino", hosted_sidecars=True,
                         browser_origin_tls_mode="managed_exact", local_only=False,
                         hostname="loopino.example.test", public_scheme="https")
        report = preflight_check(config, live_apply=False, request_tls=False)
        self.assertTrue(any("managed_exact_operator_required" in error for error in report.errors))

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
                "loopino.example.test",
                "*.sidecars.loopino.example.test",
                "af-short.sidecars.loopino.example.test",
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

    def test_covered_launch_does_not_require_other_batch_hosts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = self._settings(Path(temp_dir))
            ensure_browser_origin_tls(
                [self.app_host], group_key="session:one", settings=settings,
                run_command=lambda command: self._write_lineage(settings, command),
            )
            record_issuance_failure(settings.private_root, self.domain, settings.acme_ca, TimeoutError())

            ensure_browser_origin_tls(
                [self.app_host, self.other_host], required_hosts=[self.app_host],
                group_key="session:one", settings=settings,
                run_command=lambda _command: self.fail("Covered launches must not request other certificates"),
            )
            with self.assertRaises(BrowserOriginTlsError):
                ensure_browser_origin_tls(
                    [self.app_host, self.other_host], required_hosts=[self.other_host],
                    group_key="session:one", settings=settings,
                    run_command=lambda _command: self.fail("Backoff must still block an uncovered launch"),
                )

    def test_failed_renewal_keeps_unexpired_certificate_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = self._settings(Path(temp_dir))
            ensure_browser_origin_tls(
                [self.app_host], group_key="session:one", settings=settings,
                run_command=lambda command: self._write_lineage(settings, command, valid_for=timedelta(days=10)),
            )
            certificate_path, _key_path = managed_certificate_paths(settings.served_root, self.app_host)
            published = certificate_path.read_bytes()
            calls = []

            def fail(command: list[str]) -> None:
                calls.append(command)
                raise subprocess.CalledProcessError(1, command)

            ensure_browser_origin_tls(
                [self.app_host], group_key="session:one", settings=settings, run_command=fail,
            )
            self.assertEqual(len(calls), 1)
            self.assertIsNotNone(issuance_retry_at(settings.private_root, self.domain, settings.acme_ca))
            ensure_browser_origin_tls(
                [self.app_host], group_key="session:one", settings=settings,
                run_command=lambda _command: self.fail("Renewal must respect backoff"),
            )
            self.assertEqual(certificate_path.read_bytes(), published)

    def test_expired_certificate_does_not_authorize_launch_during_backoff(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = self._settings(Path(temp_dir))
            ensure_browser_origin_tls(
                [self.app_host], group_key="session:one", settings=settings,
                run_command=lambda command: self._write_lineage(settings, command),
            )
            certificate_path, key_path = managed_certificate_paths(settings.served_root, self.app_host)
            self._write_pair(certificate_path, key_path, dns_names=[self.app_host], valid_for=timedelta(seconds=-1))
            record_issuance_failure(settings.private_root, self.domain, settings.acme_ca, TimeoutError())

            with self.assertRaises(BrowserOriginTlsError):
                ensure_browser_origin_tls(
                    [self.app_host], group_key="session:one", settings=settings,
                    run_command=lambda _command: self.fail("Backoff must block expired certificates"),
                )

    def test_required_hosts_must_belong_to_issuance_batch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = self._settings(Path(temp_dir))
            for required_hosts in ([], [self.other_host]):
                with self.subTest(required_hosts=required_hosts), self.assertRaises(BrowserOriginTlsError):
                    ensure_browser_origin_tls(
                        [self.app_host], required_hosts=required_hosts,
                        group_key="session:one", settings=settings,
                        run_command=lambda _command: self.fail("Invalid required hosts must not issue certificates"),
                    )

    def test_certificate_expiring_during_failed_renewal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = self._settings(Path(temp_dir))
            ensure_browser_origin_tls(
                [self.app_host], group_key="session:one", settings=settings,
                run_command=lambda command: self._write_lineage(settings, command, valid_for=timedelta(days=10)),
            )
            certificate_path, key_path = managed_certificate_paths(settings.served_root, self.app_host)

            def fail(command: list[str]) -> None:
                self._write_pair(
                    certificate_path, key_path, dns_names=[self.app_host], valid_for=timedelta(seconds=-1),
                )
                raise subprocess.CalledProcessError(1, command)

            with self.assertRaises(BrowserOriginTlsError):
                ensure_browser_origin_tls(
                    [self.app_host], group_key="session:one", settings=settings, run_command=fail,
                )

    def test_ca_retry_date_defers_new_sessions_but_keeps_valid_hosts_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = self._settings(Path(temp_dir))
            ensure_browser_origin_tls([self.app_host], group_key="existing-session", settings=settings,
                run_command=lambda command: self._write_lineage(settings, command))
            retry_at = (datetime.now(timezone.utc) + timedelta(hours=2)).replace(microsecond=0)
            error = subprocess.CalledProcessError(1, ["certbot"], stderr=(
                "too many certificates; retry after " + retry_at.strftime("%Y-%m-%d %H:%M:%S UTC")).encode())
            def fail(_command):
                raise error
            with self.assertRaises(BrowserOriginTlsError):
                ensure_browser_origin_tls([self.other_host], group_key="new-session", settings=settings, run_command=fail)
            self.assertEqual(issuance_retry_at(settings.private_root, settings.installation_domain, settings.acme_ca), retry_at)
            def never_issue(_command):
                self.fail("Rate-limited sessions must not create another ACME order")
            with self.assertRaisesRegex(BrowserOriginTlsError, "temporarily unavailable"):
                ensure_browser_origin_tls([self.other_host], group_key="another-session", settings=settings, run_command=never_issue)
            ensure_browser_origin_tls([self.app_host], group_key="existing-session", settings=settings, run_command=never_issue)
            with patch("core.shared.browser_origin_tls.issuance_retry_at", return_value=retry_at - timedelta(hours=3)):
                ensure_browser_origin_tls([self.other_host], group_key="new-session", settings=settings,
                    run_command=lambda command: self._write_lineage(settings, command))
            self.assertIsNone(issuance_retry_at(settings.private_root, settings.installation_domain, settings.acme_ca))

    def test_ordinary_failures_back_off_briefly_and_other_cas_are_independent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            now = datetime.now(timezone.utc)
            record_issuance_failure(root, self.domain, "ca-one", TimeoutError(), now=now)
            self.assertEqual(issuance_retry_at(root, self.domain, "ca-one"), now + timedelta(minutes=1))
            self.assertIsNone(issuance_retry_at(root, self.domain, "ca-two"))
            self.assertIsNone(issuance_retry_at(root, "another.example.test", "ca-one"))

    def _settings(self, root: Path, *, mode: str = "managed_exact") -> BrowserOriginTlsSettings:
        return BrowserOriginTlsSettings(
            mode=mode,
            installation_domain=self.domain,
            tls_root=root / "tls",
            acme_webroot=root / "acme",
            repository_root=Path(__file__).resolve().parents[3],
            acme_ca="https://acme.test/directory",
            timeout_seconds=30,
        )

    def _write_lineage(
        self, settings: BrowserOriginTlsSettings, command: list[str], *, valid_for: timedelta = timedelta(days=90),
    ) -> None:
        cert_name = command[command.index("--cert-name") + 1]
        lineage = settings.certbot_config_root / "live" / cert_name
        lineage.mkdir(parents=True, exist_ok=True)
        self._write_pair(
            lineage / "fullchain.pem",
            lineage / "privkey.pem",
            dns_names=self._domains(command),
            valid_for=valid_for,
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
        valid_for: timedelta = timedelta(days=90),
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
            .not_valid_after(now + valid_for)
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
