"""Paths for host-owned installation material, independent of OS TLS lineages."""

from pathlib import Path


def certbot_root(repository_root: Path) -> Path:
    return repository_root / "installation/tls/certbot"


def certbot_directory_arguments(repository_root: Path) -> list[str]:
    root = certbot_root(repository_root)
    return ["--config-dir", str(root / "config"),
            "--work-dir", str(root / "work"), "--logs-dir", str(root / "logs")]


def dns_credentials_root(repository_root: Path) -> Path:
    return repository_root / "installation/tls/credentials"
