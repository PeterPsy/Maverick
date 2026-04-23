"""CLI installer helpers for Maverick deployment configuration."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
from typing import Any

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
        "nginx_conf_path": None if config.nginx_conf_path is None else str(config.nginx_conf_path),
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
