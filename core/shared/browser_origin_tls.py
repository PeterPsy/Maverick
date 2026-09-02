"""Managed exact certificates for dynamic hosted browser origins.

The managed mode is an HTTP-01 alternative for installations that cannot
provision a wildcard with DNS-01.  Core may request certificates only for its
reserved, internally derived ``af-*`` and ``sc-*`` hostnames.  Nginx reads the
atomically published copies; ACME account material remains private to Core.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import fcntl
from hashlib import sha256
import os
from pathlib import Path
import re
import secrets
import subprocess
from typing import Callable, Sequence

from cryptography import x509
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes as cryptography_hashes, serialization


EXTERNAL_WILDCARD_TLS_MODE = "external_wildcard"
MANAGED_EXACT_TLS_MODE = "managed_exact"
SUPPORTED_TLS_MODES = frozenset({EXTERNAL_WILDCARD_TLS_MODE, MANAGED_EXACT_TLS_MODE})
MAX_CERTIFICATE_NAMES = 100
RENEWAL_WINDOW = timedelta(days=30)
_DOMAIN_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)


class BrowserOriginTlsError(RuntimeError):
    """Raised when a managed browser origin cannot be served with trusted TLS."""


@dataclass(frozen=True)
class BrowserOriginTlsSettings:
    """Explicit managed-certificate paths and ACME client settings."""

    mode: str
    installation_domain: str
    tls_root: Path
    acme_webroot: Path
    certbot_command: str = "certbot"
    acme_ca: str = ""
    timeout_seconds: int = 120

    @property
    def private_root(self) -> Path:
        return self.tls_root / "private"

    @property
    def served_root(self) -> Path:
        return self.tls_root / "served"

    @property
    def certbot_config_root(self) -> Path:
        return self.private_root / "certbot" / "config"

    @property
    def certbot_work_root(self) -> Path:
        return self.private_root / "certbot" / "work"

    @property
    def certbot_logs_root(self) -> Path:
        return self.private_root / "certbot" / "logs"

    @classmethod
    def from_environment(cls, *, repository_root: Path) -> BrowserOriginTlsSettings:
        """Read runtime settings without accepting a browser-provided value."""
        default_root = repository_root / "data" / "browser-origin-tls"
        default_webroot = repository_root / "data" / "browser-origin-acme"
        timeout_text = os.environ.get("MAVERICK_BROWSER_ORIGIN_CERTBOT_TIMEOUT_SECONDS", "120")
        try:
            timeout_seconds = int(timeout_text)
        except ValueError as error:
            raise BrowserOriginTlsError("Managed browser-origin TLS timeout is invalid.") from error
        return cls(
            mode=(
                os.environ.get("MAVERICK_BROWSER_ORIGIN_TLS_MODE", EXTERNAL_WILDCARD_TLS_MODE)
                .strip()
                .lower()
                or EXTERNAL_WILDCARD_TLS_MODE
            ),
            installation_domain=(
                os.environ.get("MAVERICK_SIDECAR_INSTALLATION_DOMAIN", "").strip().lower().rstrip(".")
            ),
            tls_root=Path(os.environ.get("MAVERICK_BROWSER_ORIGIN_TLS_ROOT", str(default_root))),
            acme_webroot=Path(
                os.environ.get("MAVERICK_BROWSER_ORIGIN_ACME_WEBROOT", str(default_webroot))
            ),
            certbot_command=(
                os.environ.get("MAVERICK_BROWSER_ORIGIN_CERTBOT_COMMAND", "certbot").strip()
                or "certbot"
            ),
            acme_ca=os.environ.get("MAVERICK_BROWSER_ORIGIN_ACME_CA", "").strip(),
            timeout_seconds=timeout_seconds,
        )


def managed_browser_origin_tls_enabled() -> bool:
    """Return whether runtime exact-certificate management is explicitly enabled."""
    mode = (
        os.environ.get("MAVERICK_BROWSER_ORIGIN_TLS_MODE", EXTERNAL_WILDCARD_TLS_MODE)
        .strip()
        .lower()
        or EXTERNAL_WILDCARD_TLS_MODE
    )
    if mode not in SUPPORTED_TLS_MODES:
        raise BrowserOriginTlsError("MAVERICK_BROWSER_ORIGIN_TLS_MODE is invalid.")
    return mode == MANAGED_EXACT_TLS_MODE


def ensure_browser_origin_tls(
    hosts: Sequence[str],
    *,
    group_key: str,
    repository_root: Path | None = None,
    settings: BrowserOriginTlsSettings | None = None,
    run_command: Callable[[list[str]], object] | None = None,
) -> None:
    """Ensure every exact reserved host has a currently valid published certificate."""
    resolved = settings or BrowserOriginTlsSettings.from_environment(
        repository_root=(repository_root or Path.cwd()).resolve()
    )
    if resolved.mode == EXTERNAL_WILDCARD_TLS_MODE:
        return
    _validate_settings(resolved)
    requested = _validated_hosts(hosts, installation_domain=resolved.installation_domain)
    if not group_key or len(group_key) > 512 or "\0" in group_key:
        raise BrowserOriginTlsError("Managed browser-origin TLS group is invalid.")
    _ensure_directories(resolved)

    lock_path = resolved.private_root / "issuance.lock"
    with lock_path.open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        if all(_published_host_is_current(resolved, host) for host in requested):
            return
        _issue_and_publish(
            resolved,
            requested=requested,
            group_key=group_key,
            run_command=run_command,
        )


def managed_certificate_paths(served_root: Path, host: str) -> tuple[Path, Path]:
    """Return the Nginx-facing paths for one exact browser-origin host."""
    current = served_root / "hosts" / host / "current"
    return current / "fullchain.pem", current / "privkey.pem"


def _validate_settings(settings: BrowserOriginTlsSettings) -> None:
    if settings.mode not in SUPPORTED_TLS_MODES:
        raise BrowserOriginTlsError("MAVERICK_BROWSER_ORIGIN_TLS_MODE is invalid.")
    if settings.mode != MANAGED_EXACT_TLS_MODE:
        return
    if not settings.installation_domain or not _DOMAIN_PATTERN.fullmatch(settings.installation_domain):
        raise BrowserOriginTlsError("Managed browser-origin TLS installation domain is invalid.")
    if not settings.tls_root.is_absolute() or not settings.acme_webroot.is_absolute():
        raise BrowserOriginTlsError("Managed browser-origin TLS paths must be absolute.")
    if settings.timeout_seconds < 30 or settings.timeout_seconds > 600:
        raise BrowserOriginTlsError("Managed browser-origin TLS timeout must be between 30 and 600 seconds.")
    if not settings.certbot_command or "\0" in settings.certbot_command:
        raise BrowserOriginTlsError("Managed browser-origin TLS Certbot command is invalid.")


def _validated_hosts(hosts: Sequence[str], *, installation_domain: str) -> list[str]:
    suffix = re.escape(f".sidecars.{installation_domain}")
    pattern = re.compile(rf"^(?:af|sc)-[a-f0-9]{{24}}{suffix}$")
    normalized = sorted({str(host).strip().lower().rstrip(".") for host in hosts})
    if not normalized or len(normalized) > MAX_CERTIFICATE_NAMES:
        raise BrowserOriginTlsError("Managed browser-origin TLS requires between 1 and 100 exact names.")
    if any(not pattern.fullmatch(host) for host in normalized):
        raise BrowserOriginTlsError("Managed browser-origin TLS host is outside the reserved namespace.")
    return normalized


def _ensure_directories(settings: BrowserOriginTlsSettings) -> None:
    for path, mode in (
        (settings.private_root, 0o700),
        (settings.certbot_config_root, 0o700),
        (settings.certbot_work_root, 0o700),
        (settings.certbot_logs_root, 0o700),
        (settings.served_root, 0o750),
        (settings.served_root / "hosts", 0o750),
        (settings.served_root / "releases", 0o750),
        (settings.acme_webroot, 0o755),
    ):
        path.mkdir(parents=True, exist_ok=True)
        special_bits = path.stat().st_mode & 0o7000
        path.chmod(special_bits | mode)


def _issue_and_publish(
    settings: BrowserOriginTlsSettings,
    *,
    requested: list[str],
    group_key: str,
    run_command: Callable[[list[str]], object] | None,
) -> None:
    cert_name = f"maverick-browser-{sha256(group_key.encode('utf-8')).hexdigest()[:24]}"
    lineage_certificate = settings.certbot_config_root / "live" / cert_name / "fullchain.pem"
    lineage_private_key = settings.certbot_config_root / "live" / cert_name / "privkey.pem"
    existing_names: set[str] = set()
    if lineage_certificate.is_file() and lineage_private_key.is_file():
        try:
            existing_names = set(_validated_pair(lineage_certificate, lineage_private_key).names)
        except BrowserOriginTlsError:
            existing_names = set()
    permitted_existing = set(
        _validated_hosts(
            [name for name in existing_names if _is_reserved_host(name, settings.installation_domain)],
            installation_domain=settings.installation_domain,
        )
    ) if any(_is_reserved_host(name, settings.installation_domain) for name in existing_names) else set()
    desired = sorted(permitted_existing | set(requested))
    if len(desired) > MAX_CERTIFICATE_NAMES:
        raise BrowserOriginTlsError("Managed browser-origin TLS certificate reached its 100-name limit.")

    command = _certbot_command(settings, cert_name=cert_name, names=desired)
    if permitted_existing and set(desired) > permitted_existing:
        command.append("--expand")
    try:
        if run_command is None:
            subprocess.run(
                command,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=settings.timeout_seconds,
            )
        else:
            run_command(command)
    except (OSError, subprocess.SubprocessError) as error:
        raise BrowserOriginTlsError("Managed browser-origin certificate issuance failed.") from error

    pair = _validated_pair(lineage_certificate, lineage_private_key)
    if not set(desired).issubset(pair.names) or pair.not_valid_after <= datetime.now(timezone.utc):
        raise BrowserOriginTlsError("Managed browser-origin certificate did not cover every requested name.")
    _publish_pair(settings, pair=pair)


def _certbot_command(
    settings: BrowserOriginTlsSettings,
    *,
    cert_name: str,
    names: Sequence[str],
) -> list[str]:
    command = [
        settings.certbot_command,
        "certonly",
        "--non-interactive",
        "--agree-tos",
        "--register-unsafely-without-email",
        "--no-eff-email",
        "--webroot",
        "--webroot-path",
        str(settings.acme_webroot),
        "--preferred-challenges",
        "http",
        "--config-dir",
        str(settings.certbot_config_root),
        "--work-dir",
        str(settings.certbot_work_root),
        "--logs-dir",
        str(settings.certbot_logs_root),
        "--cert-name",
        cert_name,
        "--key-type",
        "ecdsa",
    ]
    if settings.acme_ca:
        command.extend(("--server", settings.acme_ca))
    for name in names:
        command.extend(("-d", name))
    return command


@dataclass(frozen=True)
class _CertificatePair:
    certificate_bytes: bytes
    private_key_bytes: bytes
    names: frozenset[str]
    not_valid_after: datetime
    fingerprint: str


def _validated_pair(certificate_path: Path, private_key_path: Path) -> _CertificatePair:
    try:
        certificate_bytes = certificate_path.read_bytes()
        certificates = x509.load_pem_x509_certificates(certificate_bytes)
        certificate = certificates[0]
        private_key_bytes = private_key_path.read_bytes()
        private_key = serialization.load_pem_private_key(private_key_bytes, password=None)
        names = frozenset(
            name.rstrip(".").lower()
            for name in certificate.extensions.get_extension_for_class(
                x509.SubjectAlternativeName
            ).value.get_values_for_type(x509.DNSName)
        )
        certificate_key = certificate.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        private_public_key = private_key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    except (IndexError, OSError, TypeError, ValueError, UnsupportedAlgorithm, x509.ExtensionNotFound) as error:
        raise BrowserOriginTlsError("Managed browser-origin certificate material is invalid.") from error
    if not secrets.compare_digest(certificate_key, private_public_key):
        raise BrowserOriginTlsError("Managed browser-origin certificate and private key do not match.")
    now = datetime.now(timezone.utc)
    if certificate.not_valid_before_utc > now or certificate.not_valid_after_utc <= now:
        raise BrowserOriginTlsError("Managed browser-origin certificate is not currently valid.")
    return _CertificatePair(
        certificate_bytes=certificate_bytes,
        private_key_bytes=private_key_bytes,
        names=names,
        not_valid_after=certificate.not_valid_after_utc,
        fingerprint=certificate.fingerprint(cryptography_hashes.SHA256()).hex(),
    )


def _published_host_is_current(settings: BrowserOriginTlsSettings, host: str) -> bool:
    certificate_path, private_key_path = managed_certificate_paths(settings.served_root, host)
    if not certificate_path.is_file() or not private_key_path.is_file():
        return False
    try:
        pair = _validated_pair(certificate_path, private_key_path)
    except BrowserOriginTlsError:
        return False
    return host in pair.names and pair.not_valid_after - datetime.now(timezone.utc) > RENEWAL_WINDOW


def _publish_pair(
    settings: BrowserOriginTlsSettings,
    *,
    pair: _CertificatePair,
) -> None:
    release = settings.served_root / "releases" / pair.fingerprint
    release.mkdir(mode=0o750, parents=True, exist_ok=True)
    published_certificate = release / "fullchain.pem"
    published_key = release / "privkey.pem"
    _atomic_write(published_certificate, pair.certificate_bytes, mode=0o644)
    _atomic_write(published_key, pair.private_key_bytes, mode=0o640)
    for host in sorted(pair.names):
        if not _is_reserved_host(host, settings.installation_domain):
            continue
        host_root = settings.served_root / "hosts" / host
        host_root.mkdir(mode=0o750, parents=True, exist_ok=True)
        temporary = host_root / f".current-{os.getpid()}"
        try:
            temporary.unlink(missing_ok=True)
            temporary.symlink_to(Path("..") / ".." / "releases" / pair.fingerprint)
            os.replace(temporary, host_root / "current")
        finally:
            temporary.unlink(missing_ok=True)


def _atomic_write(path: Path, content: bytes, *, mode: int) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(content)
        temporary.chmod(mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _is_reserved_host(host: str, installation_domain: str) -> bool:
    suffix = re.escape(f".sidecars.{installation_domain}")
    return re.fullmatch(rf"(?:af|sc)-[a-f0-9]{{24}}{suffix}", host) is not None


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installation-domain", required=True)
    parser.add_argument("--tls-root", type=Path, required=True)
    parser.add_argument("--acme-webroot", type=Path, required=True)
    parser.add_argument("--group-key", required=True)
    parser.add_argument("--host", action="append", required=True)
    parser.add_argument("--certbot-command", default="certbot")
    parser.add_argument("--acme-ca", default="")
    args = parser.parse_args(argv)
    ensure_browser_origin_tls(
        args.host,
        group_key=args.group_key,
        settings=BrowserOriginTlsSettings(
            mode=MANAGED_EXACT_TLS_MODE,
            installation_domain=args.installation_domain,
            tls_root=args.tls_root,
            acme_webroot=args.acme_webroot,
            certbot_command=args.certbot_command,
            acme_ca=args.acme_ca,
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
