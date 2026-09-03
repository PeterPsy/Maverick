"""Hosted-sidecar TLS validation and post-install origin probing."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
from typing import Any, Callable
from urllib import error, request

from cryptography import x509
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization

from core.shared.browser_origin_tls import managed_certificate_paths


SIDECAR_TLS_PROBE_LABEL = "sc-000000000000000000000000"
APP_FRAME_TLS_PROBE_LABEL = "af-000000000000000000000000"


def hosted_sidecar_tls_errors(
    *,
    hostname: str,
    certificate_path_value: str,
    private_key_path_value: str,
) -> list[str]:
    """Validate the exact wildcard leaf, validity window, and matching key."""
    certificate_path = Path(certificate_path_value)
    private_key_path = Path(private_key_path_value)
    errors: list[str] = []
    certificate_available = _regular_file_available(certificate_path)
    private_key_available = _regular_file_available(private_key_path)
    if not certificate_available:
        errors.append(f"hosted sidecar TLS certificate not found: {certificate_path}")
    if not private_key_available:
        errors.append(f"hosted sidecar TLS private key not found: {private_key_path}")
    if not certificate_available or not private_key_available:
        return errors

    certificate: x509.Certificate | None = None
    private_key: Any = None
    try:
        certificates = x509.load_pem_x509_certificates(certificate_path.read_bytes())
        if certificates:
            certificate = certificates[0]
    except (OSError, ValueError):
        certificate = None
    if certificate is None:
        errors.append(f"hosted sidecar TLS certificate is not valid PEM: {certificate_path}")
    else:
        expected_name = f"*.sidecars.{hostname}".lower()
        try:
            names = certificate.extensions.get_extension_for_class(
                x509.SubjectAlternativeName
            ).value.get_values_for_type(x509.DNSName)
        except x509.ExtensionNotFound:
            names = []
        if expected_name not in {name.rstrip(".").lower() for name in names}:
            errors.append(
                "hosted sidecar TLS certificate SAN does not include required wildcard: "
                f"{expected_name}"
            )
        now = datetime.now(timezone.utc)
        if certificate.not_valid_before_utc > now or certificate.not_valid_after_utc < now:
            errors.append("hosted sidecar TLS certificate is not currently valid")

    try:
        private_key = serialization.load_pem_private_key(
            private_key_path.read_bytes(),
            password=None,
        )
    except (OSError, TypeError, ValueError, UnsupportedAlgorithm):
        errors.append(
            f"hosted sidecar TLS private key is not valid unencrypted PEM: {private_key_path}"
        )

    if certificate is not None and private_key is not None:
        certificate_public_key = certificate.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        private_public_key = private_key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        if not secrets.compare_digest(certificate_public_key, private_public_key):
            errors.append("hosted sidecar TLS certificate and private key do not match")
    return errors


def sidecar_tls_probe_url(hostname: str) -> str:
    return f"https://{SIDECAR_TLS_PROBE_LABEL}.sidecars.{hostname}/"


def app_frame_tls_probe_url(hostname: str) -> str:
    return f"https://{APP_FRAME_TLS_PROBE_LABEL}.sidecars.{hostname}/"


def managed_browser_origin_tls_errors(*, hostname: str, tls_root_value: str) -> list[str]:
    """Validate both exact probe certificates published for dynamic Nginx TLS."""
    served_root = Path(tls_root_value) / "served"
    errors: list[str] = []
    for label in (SIDECAR_TLS_PROBE_LABEL, APP_FRAME_TLS_PROBE_LABEL):
        host = f"{label}.sidecars.{hostname}"
        certificate_path, private_key_path = managed_certificate_paths(served_root, host)
        errors.extend(
            _managed_exact_pair_errors(
                host=host,
                certificate_path=certificate_path,
                private_key_path=private_key_path,
            )
        )
    return errors


def _managed_exact_pair_errors(
    *,
    host: str,
    certificate_path: Path,
    private_key_path: Path,
) -> list[str]:
    errors: list[str] = []
    certificate_available = _regular_file_available(certificate_path)
    private_key_available = _regular_file_available(private_key_path)
    if not certificate_available:
        errors.append(f"managed browser-origin TLS certificate not found for {host}: {certificate_path}")
    if not private_key_available:
        errors.append(f"managed browser-origin TLS private key not found for {host}: {private_key_path}")
    if not certificate_available or not private_key_available:
        return errors
    try:
        certificates = x509.load_pem_x509_certificates(certificate_path.read_bytes())
        certificate = certificates[0]
        names = {
            name.rstrip(".").lower()
            for name in certificate.extensions.get_extension_for_class(
                x509.SubjectAlternativeName
            ).value.get_values_for_type(x509.DNSName)
        }
    except (IndexError, OSError, ValueError, x509.ExtensionNotFound):
        return [f"managed browser-origin TLS certificate is invalid for {host}: {certificate_path}"]
    if host not in names:
        errors.append(f"managed browser-origin TLS certificate SAN does not include exact host: {host}")
    now = datetime.now(timezone.utc)
    if certificate.not_valid_before_utc > now or certificate.not_valid_after_utc < now:
        errors.append(f"managed browser-origin TLS certificate is not currently valid for {host}")
    try:
        private_key = serialization.load_pem_private_key(private_key_path.read_bytes(), password=None)
        certificate_key = certificate.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        private_public_key = private_key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    except (OSError, TypeError, ValueError, UnsupportedAlgorithm):
        errors.append(f"managed browser-origin TLS private key is invalid for {host}: {private_key_path}")
    else:
        if not secrets.compare_digest(certificate_key, private_public_key):
            errors.append(f"managed browser-origin TLS certificate and private key do not match for {host}")
    return errors


def hosted_browser_origin_becomes_healthy(
    url: str,
    *,
    expected_error: str,
    timeout_seconds: float,
    attempts: int,
    delay_seconds: float,
    sleep_func: Callable[[float], None],
) -> bool:
    total_attempts = max(1, attempts)
    for attempt in range(total_attempts):
        if hosted_browser_origin_is_healthy(
            url,
            timeout_seconds=timeout_seconds,
            expected_error=expected_error,
        ):
            return True
        if attempt < total_attempts - 1 and delay_seconds > 0:
            sleep_func(delay_seconds)
    return False


def hosted_browser_origin_is_healthy(
    url: str,
    *,
    timeout_seconds: float,
    expected_error: str,
) -> bool:
    """Verify that public DNS/TLS reaches the exact reserved-origin router."""
    if not expected_error:
        return False
    try:
        with request.urlopen(url, timeout=timeout_seconds):
            return False
    except error.HTTPError as exc:
        if exc.code != 401:
            return False
        try:
            payload = json.loads(exc.read(4096).decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return False
        return payload == {"error": expected_error}
    except (error.URLError, TimeoutError, ValueError):
        return False


def _regular_file_available(path: Path) -> bool:
    try:
        return bool(str(path)) and path.is_file()
    except OSError:
        return False
