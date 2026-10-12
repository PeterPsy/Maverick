"""Validate public installation identities before any host mutation."""

import ipaddress
import re
from urllib.parse import urlsplit

from core.installation.errors import InstallationError


def hostname(value: str) -> str:
    if not isinstance(value, str) or any(c.isspace() for c in value):
        raise InstallationError("invalid_hostname")
    try:
        parsed = urlsplit(value if "://" in value else "https://" + value)
        port = parsed.port
    except ValueError:
        raise InstallationError("invalid_hostname") from None
    if (parsed.scheme != "https" or parsed.username or parsed.password or port
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
        raise InstallationError("invalid_hostname")
    try:
        host = (parsed.hostname or "").rstrip(".").encode("idna").decode().lower()
    except UnicodeError:
        raise InstallationError("invalid_hostname") from None
    labels = host.split(".")
    if (len(host) > 216 or len(labels) < 2 or labels[-1] in {"localhost", "local", "internal", "test", "invalid"}
            or not re.fullmatch(r"[a-z]{2,63}", labels[-1])
            or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels)):
        raise InstallationError("invalid_hostname")
    return host


def public_ip(value: str) -> str:
    try:
        address = ipaddress.ip_address(value)
    except (ValueError, TypeError):
        raise InstallationError("invalid_server_ip") from None
    if not address.is_global:
        raise InstallationError("public_server_ip_required")
    return str(address)


def secret_ref(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"platform:(?:secrets|secret-alias)/[a-z0-9][a-z0-9._-]{1,126}", value):
        raise InstallationError("invalid_dns_credential_ref")
    return value


def record_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value):
        raise InstallationError("invalid_record_id")
    return value
