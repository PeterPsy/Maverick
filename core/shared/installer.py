"""CLI installer helpers for Maverick deployment configuration."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any
from urllib import error, request

from core.shared.repository import installation_paths


@dataclass(frozen=True)
class InstallerConfig:
    """Explicit parameters for one Maverick installation rendering pass."""

    repository_root: Path
    install_root: Path
    output_root: Path
    service_user: str
    service_group: str
    bind_host: str
    hostname: str | None
    public_scheme: str
    core_port: int
    rescue_port: int
    bootstrap: bool
    verify: bool
    local_only: bool
    acme_root: Path | None
    systemd_dir: Path
    nginx_conf_path: Path | None
    live_systemd_dir: Path
    live_nginx_conf_path: Path | None
    live_nginx_enabled_path: Path | None

    @property
    def public_url(self) -> str:
        if self.local_only or not self.hostname:
            return f"http://{self.bind_host}:{self.core_port}"
        return f"{self.public_scheme}://{self.hostname}"

    @property
    def tls_certificate_path(self) -> str:
        if not self.hostname:
            return ""
        return f"/etc/letsencrypt/live/{self.hostname}/fullchain.pem"

    @property
    def tls_certificate_key_path(self) -> str:
        if not self.hostname:
            return ""
        return f"/etc/letsencrypt/live/{self.hostname}/privkey.pem"


def render_install_plan(config: InstallerConfig) -> dict[Path, str]:
    """Render the systemd/nginx/install manifest files for one installer run."""
    templates_root = config.repository_root / "scripts" / "deploy"
    substitutions = {
        "{{SERVICE_USER}}": config.service_user,
        "{{SERVICE_GROUP}}": config.service_group,
        "{{INSTALL_ROOT}}": str(config.install_root),
        "{{BIND_HOST}}": config.bind_host,
        "{{CORE_PORT}}": str(config.core_port),
        "{{RESCUE_PORT}}": str(config.rescue_port),
        "{{HOSTNAME}}": config.hostname or "",
        "{{ACME_ROOT}}": str(config.acme_root or Path("/var/www/localhost")),
        "{{TLS_CERT_PATH}}": config.tls_certificate_path,
        "{{TLS_CERT_KEY_PATH}}": config.tls_certificate_key_path,
    }

    outputs: dict[Path, str] = {}
    for template_path in sorted((templates_root / "systemd").glob("*")):
        rendered = _render_template(template_path, substitutions)
        outputs[config.systemd_dir / template_path.name] = rendered
    if config.nginx_conf_path is not None:
        rendered = _render_template(templates_root / "nginx" / "maverick.example.conf", substitutions)
        outputs[config.nginx_conf_path] = rendered
    outputs[config.output_root / "install-manifest.json"] = json.dumps(build_install_manifest(config), indent=2) + "\n"
    return outputs


def build_install_manifest(config: InstallerConfig) -> dict[str, Any]:
    """Return a machine-readable summary for one installation plan."""
    return {
        "schema_version": "1",
        "install_root": str(config.install_root),
        "public_url": config.public_url,
        "bind_host": config.bind_host,
        "core_port": config.core_port,
        "rescue_port": config.rescue_port,
        "service_user": config.service_user,
        "service_group": config.service_group,
        "local_only": config.local_only,
        "hostname": config.hostname,
        "systemd_dir": str(config.systemd_dir),
        "live_systemd_dir": str(config.live_systemd_dir),
        "nginx_conf_path": None if config.nginx_conf_path is None else str(config.nginx_conf_path),
        "live_nginx_conf_path": None if config.live_nginx_conf_path is None else str(config.live_nginx_conf_path),
        "live_nginx_enabled_path": None if config.live_nginx_enabled_path is None else str(config.live_nginx_enabled_path),
        "acme_root": None if config.acme_root is None else str(config.acme_root),
        "bootstrap_requested": config.bootstrap,
        "verify_requested": config.verify,
    }


def write_install_plan(files: dict[Path, str]) -> None:
    """Persist rendered installer files."""
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def run_install_steps(config: InstallerConfig) -> None:
    """Run the requested bootstrap/verification steps for one installer invocation."""
    repository_root = config.repository_root
    if config.bootstrap:
        subprocess.run([str(repository_root / "scripts" / "bootstrap_local.sh")], cwd=repository_root, check=True)
    if config.verify:
        subprocess.run([str(repository_root / "scripts" / "verify_local.sh")], cwd=repository_root, check=True)


def preflight_check(config: InstallerConfig) -> list[str]:
    """Return human-readable warnings for missing optional dependencies."""
    warnings: list[str] = []
    if shutil.which("systemctl") is None:
        warnings.append("systemctl not found in PATH")
    if not config.local_only and shutil.which("nginx") is None:
        warnings.append("nginx not found in PATH")
    if not config.local_only and config.public_scheme == "https" and shutil.which("certbot") is None:
        warnings.append("certbot not found in PATH")
    if shutil.which("bubblewrap") is None and shutil.which("bwrap") is None:
        warnings.append("bubblewrap not found in PATH")
    if shutil.which("codex") is None:
        warnings.append("codex not found in PATH")
    return warnings


def apply_install_plan(
    config: InstallerConfig,
    rendered_files: dict[Path, str],
    *,
    run_command: Any = None,
) -> None:
    """Apply the rendered install plan to live system paths."""
    runner = run_command or run_privileged_command
    _write_tree(rendered_files, source_root=config.systemd_dir, destination_root=config.live_systemd_dir)
    if config.nginx_conf_path is not None and config.live_nginx_conf_path is not None:
        nginx_content = rendered_files.get(config.nginx_conf_path)
        if nginx_content is None and config.nginx_conf_path.is_file():
            nginx_content = config.nginx_conf_path.read_text(encoding="utf-8")
        if nginx_content is None:
            raise FileNotFoundError(f"Rendered nginx config missing at `{config.nginx_conf_path}`.")
        _write_file(config.live_nginx_conf_path, nginx_content)
        if config.live_nginx_enabled_path is not None:
            _ensure_symlink(config.live_nginx_enabled_path, config.live_nginx_conf_path)
    if config.acme_root is not None:
        runner(["mkdir", "-p", str(config.acme_root)])
    runner(["systemctl", "daemon-reload"])
    runner(["systemctl", "enable", "maverick3-core.service"])
    runner(["systemctl", "enable", "maverick3-rescue.service"])
    runner(["systemctl", "enable", "maverick3-backend-watchdog.timer"])
    runner(["systemctl", "restart", "maverick3-core.service"])
    runner(["systemctl", "restart", "maverick3-rescue.service"])
    runner(["systemctl", "start", "maverick3-backend-watchdog.timer"])
    if config.live_nginx_conf_path is not None:
        runner(["nginx", "-t"])
        runner(["systemctl", "reload", "nginx"])


def request_tls_certificate(config: InstallerConfig, *, run_command: Any = None) -> None:
    """Request or renew the public TLS certificate for one hostname."""
    if config.local_only or not config.hostname or config.acme_root is None:
        return
    runner = run_command or run_privileged_command
    runner(["mkdir", "-p", str(config.acme_root)])
    runner(
        [
            "certbot",
            "certonly",
            "--webroot",
            "-w",
            str(config.acme_root),
            "-d",
            config.hostname,
        ]
    )
    runner(["nginx", "-t"])
    runner(["systemctl", "reload", "nginx"])


def check_health(config: InstallerConfig, *, timeout_seconds: float = 5.0) -> dict[str, bool]:
    """Return local/public health availability after install."""
    health: dict[str, bool] = {
        f"http://{config.bind_host}:{config.core_port}/health": _url_is_healthy(
            f"http://{config.bind_host}:{config.core_port}/health",
            timeout_seconds=timeout_seconds,
        )
    }
    if not config.local_only and config.hostname:
        health[f"{config.public_scheme}://{config.hostname}/health"] = _url_is_healthy(
            f"{config.public_scheme}://{config.hostname}/health",
            timeout_seconds=timeout_seconds,
        )
    return health


def default_output_root(repository_root: Path) -> Path:
    """Return the default installer output root inside the repository."""
    return repository_root / ".maverick" / "install"


def default_systemd_dir(output_root: Path) -> Path:
    """Return the default systemd rendering directory."""
    return output_root / "systemd"


def default_nginx_conf_path(output_root: Path, *, hostname: str | None) -> Path | None:
    """Return the default nginx config output path."""
    if not hostname:
        return None
    return output_root / "nginx" / f"{hostname}.conf"


def default_live_systemd_dir() -> Path:
    """Return the default live systemd target path."""
    return Path("/etc/systemd/system")


def default_live_nginx_conf_path(*, hostname: str | None) -> Path | None:
    """Return the default live nginx config target path."""
    if not hostname:
        return None
    return Path("/etc/nginx/sites-available") / f"{hostname}.conf"


def default_live_nginx_enabled_path(*, hostname: str | None) -> Path | None:
    """Return the default nginx sites-enabled symlink path."""
    if not hostname:
        return None
    return Path("/etc/nginx/sites-enabled") / f"{hostname}.conf"


def default_install_root(start_path: Path | None = None) -> Path:
    """Return the current repository root as the default install target."""
    return installation_paths(start_path=start_path).repository_root


def _render_template(path: Path, substitutions: dict[str, str]) -> str:
    content = path.read_text(encoding="utf-8")
    for token, value in substitutions.items():
        content = content.replace(token, value)
    unresolved = [line for line in content.splitlines() if "{{" in line or "}}" in line]
    if unresolved:
        raise ValueError(f"Unresolved installer template placeholders in `{path}`.")
    return content


def run_privileged_command(command: list[str]) -> None:
    """Run one installer command, adding sudo when required."""
    if os.geteuid() == 0:
        subprocess.run(command, check=True)
        return
    subprocess.run(["sudo", *command], check=True)


def _write_tree(files: dict[Path, str], *, source_root: Path, destination_root: Path) -> None:
    for source_path, content in files.items():
        if not _is_relative_to(source_path, source_root):
            continue
        target_path = destination_root / source_path.relative_to(source_root)
        _write_file(target_path, content)


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _ensure_symlink(link_path: Path, target_path: Path) -> None:
    link_path.parent.mkdir(parents=True, exist_ok=True)
    if link_path.is_symlink() or link_path.exists():
        link_path.unlink()
    link_path.symlink_to(target_path)


def _url_is_healthy(url: str, *, timeout_seconds: float) -> bool:
    try:
        with request.urlopen(url, timeout=timeout_seconds) as response:
            return 200 <= response.status < 300
    except (error.URLError, TimeoutError, ValueError):
        return False


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
