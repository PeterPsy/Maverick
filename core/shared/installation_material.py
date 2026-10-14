"""Paths for host-owned installation material, independent of OS TLS lineages."""

from pathlib import Path
import stat
import subprocess


def certbot_executable(repository_root: Path) -> Path:
    """Select only the installation's explicit isolated Certbot entrypoint."""
    return repository_root / "scripts/deploy/loopino-certbot"


def validate_certbot_executable(repository_root: Path) -> None:
    path = certbot_executable(repository_root)
    if not path.is_absolute():
        raise ValueError("Certbot requires an absolute installation root")
    for executable in (path, repository_root / ".venv/bin/certbot", repository_root / "scripts/deploy/isolated_certbot.py"):
        for component in (executable, *executable.parents):
            metadata = component.lstat()
            expected = stat.S_ISREG if component == executable else stat.S_ISDIR
            if not expected(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o022:
                raise ValueError("Certbot must have protected root-owned real executable/ancestor paths")
    if not path.stat().st_mode & 0o111:
        raise ValueError("Installation Certbot is not executable")


def certbot_preflight(repository_root: Path) -> None:
    validate_certbot_executable(repository_root)
    result = subprocess.run([str(certbot_executable(repository_root)), "plugins", "--text",
                             *certbot_directory_arguments(repository_root)],
                            capture_output=True, text=True, timeout=30)
    if result.returncode or "dns-cloudflare" not in result.stdout:
        raise ValueError("Installation Certbot requires the dns-cloudflare plugin")


def certbot_root(repository_root: Path) -> Path:
    return repository_root / "installation/tls/certbot"


def certbot_directory_arguments(repository_root: Path) -> list[str]:
    root = certbot_root(repository_root)
    return ["--config-dir", str(root / "config"),
            "--work-dir", str(root / "work"), "--logs-dir", str(root / "logs")]


def dns_credentials_root(repository_root: Path) -> Path:
    return repository_root / "installation/tls/credentials"
