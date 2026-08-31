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


SIDECAR_TLS_PROBE_LABEL = "sc-000000000000000000000000"


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


def sidecar_tls_origin_becomes_healthy(
    url: str,
    *,
    timeout_seconds: float,
    attempts: int,
    delay_seconds: float,
    sleep_func: Callable[[float], None],
) -> bool:
    total_attempts = max(1, attempts)
    for attempt in range(total_attempts):
        if sidecar_tls_origin_is_healthy(url, timeout_seconds=timeout_seconds):
            return True
        if attempt < total_attempts - 1 and delay_seconds > 0:
            sleep_func(delay_seconds)
    return False


def sidecar_tls_origin_is_healthy(url: str, *, timeout_seconds: float) -> bool:
    """Verify public DNS/TLS and that Core recognizes one reserved sidecar host."""
    try:
        with request.urlopen(url, timeout=timeout_seconds) as response:
            return 200 <= response.status < 300
    except error.HTTPError as exc:
        if exc.code != 401:
            return False
        try:
            payload = json.loads(exc.read(4096).decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return False
        return payload == {"error": "session_required"}
    except (error.URLError, TimeoutError, ValueError):
        return False


def _regular_file_available(path: Path) -> bool:
    try:
        return bool(str(path)) and path.is_file()
    except OSError:
        return False
