"""CLI installer helpers for Maverick deployment configuration."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import secrets
import subprocess
import tempfile
import time
from typing import Any
from urllib import error, request

from core.shared.env_file import quote_env_value, read_env_file, unquote_env_value
from core.secrets.errors import SecretNotFoundError
from core.secrets.key_material import secret_store_key_from_text
from core.secrets.service import create_platform_secret
from core.secrets.store import SecretCollections, SecretDocumentStore
from core.shared.json_file_collection import JsonFileCollection
from core.shared.repository import installation_paths

DEFAULT_MONGODB_PASSWORD_REF = "platform:secret-alias/mongodb-password"


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
    install_env_path: Path
    live_systemd_dir: Path
    live_nginx_conf_path: Path | None
    live_nginx_enabled_path: Path | None
    build_frontends: bool
    control_store: str = "json"
    json_control_store_root: str = "data/control-plane/json"
    mongodb_uri: str = "mongodb://127.0.0.1:27017/maverick"
    mongodb_database: str = "maverick"
    mongodb_username: str = ""
    mongodb_password_ref: str = ""
    mongodb_password: str = ""
    secret_key_file: str = "data/bootstrap-secrets/secret-store.key"
    bootstrap_secret_store_root: str = "data/bootstrap-secrets"
    runtime_api_secret_ref: str = "platform:secret-alias/runtime-api-secret"
    widget_context_secret_ref: str = "platform:secret-alias/widget-context-secret"

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
    substitutions = _template_substitutions(config)
    secret_key_path, secret_key_content = _render_secret_key_file(config)

    outputs: dict[Path, str] = {}
    for template_path in sorted((templates_root / "systemd").glob("*")):
        rendered = _render_template(template_path, substitutions)
        outputs[config.systemd_dir / template_path.name] = rendered
    if config.nginx_conf_path is not None:
        outputs[config.nginx_conf_path] = render_nginx_config(config)
    outputs[secret_key_path] = secret_key_content
    outputs.update(_render_bootstrap_secret_files(config, key_text=secret_key_content.strip()))
    outputs[config.install_env_path] = render_install_env_file(config)
    outputs[config.output_root / "install-manifest.json"] = json.dumps(build_install_manifest(config), indent=2) + "\n"
    return outputs


def render_nginx_config(config: InstallerConfig, *, force_https: bool = False) -> str:
    """Render nginx config that is safe before and after TLS certificates exist."""
    templates_root = config.repository_root / "scripts" / "deploy" / "nginx"
    template_name = "maverick.example.conf" if force_https or _tls_certificate_files_exist(config) else "maverick.http.conf"
    return _render_template(templates_root / template_name, _template_substitutions(config))


def render_install_env_file(config: InstallerConfig) -> str:
    """Render the service environment file, preserving existing generated secrets."""
    existing = read_env_file(config.install_env_path)
    values = {
        "MAVERICK_ENV": existing.get("MAVERICK_ENV") or "local",
        "MAVERICK_HOST": existing.get("MAVERICK_HOST") or config.bind_host,
        "MAVERICK_PORT": existing.get("MAVERICK_PORT") or str(config.core_port),
        "MAVERICK_API_BASE": existing.get("MAVERICK_API_BASE") or f"http://{config.bind_host}:{config.core_port}",
        "MAVERICK_CORE_HEALTH_URL": existing.get("MAVERICK_CORE_HEALTH_URL") or f"http://{config.bind_host}:{config.core_port}/health",
        "MAVERICK_ADMIN_USERNAME": existing.get("MAVERICK_ADMIN_USERNAME") or "admin",
        "MAVERICK_SECRET_KEY_FILE": config.secret_key_file,
        "MAVERICK_BOOTSTRAP_SECRET_STORE_ROOT": config.bootstrap_secret_store_root,
        "MAVERICK_RUNTIME_API_SECRET_REF": config.runtime_api_secret_ref,
        "MAVERICK_WIDGET_CONTEXT_SECRET_REF": config.widget_context_secret_ref,
        "MAVERICK_CONTROL_STORE": config.control_store,
        "MAVERICK_JSON_CONTROL_STORE_ROOT": config.json_control_store_root,
        "MAVERICK_APP_STORE_URL": existing.get("MAVERICK_APP_STORE_URL") or "https://maverick-app-store.versy.ai",
    }
    if config.control_store == "mongo":
        mongodb_password_ref = config.mongodb_password_ref or (DEFAULT_MONGODB_PASSWORD_REF if config.mongodb_password else "")
        values["MAVERICK_MONGODB_URI"] = config.mongodb_uri
        values["MAVERICK_MONGODB_DATABASE"] = config.mongodb_database
        if config.mongodb_username:
            values["MAVERICK_MONGODB_USERNAME"] = config.mongodb_username
        if mongodb_password_ref:
            values["MAVERICK_MONGODB_PASSWORD_REF"] = mongodb_password_ref
    if existing.get("MAVERICK_CODEX_COMMAND"):
        values["MAVERICK_CODEX_COMMAND"] = existing["MAVERICK_CODEX_COMMAND"]
    if existing.get("MAVERICK_BACKEND_RESCUE_COMMAND"):
        values["MAVERICK_BACKEND_RESCUE_COMMAND"] = existing["MAVERICK_BACKEND_RESCUE_COMMAND"]
    lines = [
        "# Generated by scripts/install_maverick.py.",
        "# Contains local bootstrap credentials and secret refs; keep permissions restricted.",
    ]
    lines.extend(f"{key}={quote_env_value(value)}" for key, value in values.items())
    return "\n".join(lines) + "\n"


def _render_secret_key_file(config: InstallerConfig) -> tuple[Path, str]:
    path = _install_relative_path(config, config.secret_key_file)
    if path.is_file():
        content = path.read_text(encoding="utf-8").strip()
    else:
        content = secrets.token_urlsafe(32)
    if not content:
        raise RuntimeError(f"Secret key file is empty: {path}")
    return path, content + "\n"


def _render_bootstrap_secret_files(config: InstallerConfig, *, key_text: str) -> dict[Path, str]:
    root = _install_relative_path(config, config.bootstrap_secret_store_root)
    paths = {
        "secrets": root / "secrets.json",
        "values": root / "values.json",
        "bindings": root / "bindings.json",
    }
    if all(path.is_file() for path in paths.values()) and not config.mongodb_password:
        return {path: path.read_text(encoding="utf-8") for path in paths.values()}

    existing = read_env_file(config.install_env_path)
    runtime_raw_value = existing.get("MAVERICK_RUNTIME_API_SECRET") or secrets.token_urlsafe(32)
    widget_raw_value = existing.get("MAVERICK_WIDGET_CONTEXT_SECRET") or secrets.token_urlsafe(32)
    with tempfile.TemporaryDirectory(prefix="maverick-bootstrap-secrets-") as temp_dir:
        temp_root = Path(temp_dir)
        store = SecretDocumentStore(
            SecretCollections(
                secrets=JsonFileCollection(temp_root / "secrets.json"),
                values=JsonFileCollection(temp_root / "values.json"),
                bindings=JsonFileCollection(temp_root / "bindings.json"),
            ),
            key_loader=lambda: secret_store_key_from_text(key_text),
        )
        for name, path in paths.items():
            if path.is_file():
                (temp_root / f"{name}.json").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        _ensure_platform_secret(
            store,
            label="Runtime API Secret",
            raw_value=runtime_raw_value,
            alias=_alias_from_secret_ref(config.runtime_api_secret_ref),
        )
        _ensure_platform_secret(
            store,
            label="Widget Context Secret",
            raw_value=widget_raw_value,
            alias=_alias_from_secret_ref(config.widget_context_secret_ref),
        )
        if config.mongodb_password:
            _ensure_platform_secret(
                store,
                label="MongoDB Password",
                raw_value=config.mongodb_password,
                alias=_alias_from_secret_ref(config.mongodb_password_ref or DEFAULT_MONGODB_PASSWORD_REF),
                rotate=True,
            )
        if not (temp_root / "bindings.json").is_file():
            (temp_root / "bindings.json").write_text("[]\n", encoding="utf-8")
        return {
            paths["secrets"]: (temp_root / "secrets.json").read_text(encoding="utf-8"),
            paths["values"]: (temp_root / "values.json").read_text(encoding="utf-8"),
            paths["bindings"]: (temp_root / "bindings.json").read_text(encoding="utf-8"),
        }


def _ensure_platform_secret(
    store: SecretDocumentStore,
    *,
    label: str,
    raw_value: str,
    alias: str,
    rotate: bool = False,
) -> None:
    try:
        record = store.get_secret_by_alias(alias)
    except SecretNotFoundError:
        create_platform_secret(store, label=label, raw_value=raw_value, alias=alias)
        return
    if rotate:
        store.save_secret_value(secret_id=record.secret_id, raw_value=raw_value)


def _alias_from_secret_ref(secret_ref: str) -> str:
    prefix = "platform:secret-alias/"
    normalized = secret_ref.strip().lower()
    if not normalized.startswith(prefix):
        raise RuntimeError("Installer-managed bootstrap secrets must use platform:secret-alias refs.")
    return normalized.removeprefix(prefix)


def _install_relative_path(config: InstallerConfig, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return config.install_root / path


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
        "install_env_path": str(config.install_env_path),
        "live_systemd_dir": str(config.live_systemd_dir),
        "nginx_conf_path": None if config.nginx_conf_path is None else str(config.nginx_conf_path),
        "live_nginx_conf_path": None if config.live_nginx_conf_path is None else str(config.live_nginx_conf_path),
        "live_nginx_enabled_path": None if config.live_nginx_enabled_path is None else str(config.live_nginx_enabled_path),
        "acme_root": None if config.acme_root is None else str(config.acme_root),
        "bootstrap_requested": config.bootstrap,
        "verify_requested": config.verify,
        "build_frontends_requested": config.build_frontends,
    }


def write_install_plan(files: dict[Path, str]) -> None:
    """Persist rendered installer files."""
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        if path.name in {"maverick.env", ".env.maverick", ".env"}:
            path.chmod(0o600)
        if path.name == "secret-store.key" or path.parent.name == "bootstrap-secrets":
            path.chmod(0o600)


def run_install_steps(config: InstallerConfig) -> None:
    """Run the requested bootstrap/verification steps for one installer invocation."""
    repository_root = config.repository_root
    if config.bootstrap:
        env = dict(os.environ)
        if config.build_frontends:
            env["MAVERICK_BUILD_FRONTENDS"] = "1"
        subprocess.run([str(repository_root / "scripts" / "bootstrap_local.sh")], cwd=repository_root, env=env, check=True)
    if config.verify:
        subprocess.run([str(repository_root / "scripts" / "verify_local.sh")], cwd=repository_root, check=True)


@dataclass(frozen=True)
class PreflightReport:
    """Installer preflight diagnostics split by severity."""

    errors: list[str]
    warnings: list[str]


def preflight_check(
    config: InstallerConfig,
    *,
    live_apply: bool,
    request_tls: bool,
) -> PreflightReport:
    """Return diagnostics for missing installer dependencies."""
    errors: list[str] = []
    warnings: list[str] = []
    if live_apply and shutil.which("systemctl") is None:
        errors.append("systemctl not found in PATH")
    if live_apply and not config.local_only and shutil.which("nginx") is None:
        errors.append("nginx not found in PATH")
    if request_tls and shutil.which("certbot") is None:
        errors.append("certbot not found in PATH")
    if config.build_frontends:
        if shutil.which("node") is None:
            errors.append("node not found in PATH")
        if shutil.which("npm") is None:
            errors.append("npm not found in PATH")
    if live_apply and shutil.which("bubblewrap") is None and shutil.which("bwrap") is None:
        errors.append("bubblewrap not found in PATH")
    if shutil.which("python3") is None:
        errors.append("python3 not found in PATH")
    return PreflightReport(errors=errors, warnings=warnings)


def apply_install_plan(
    config: InstallerConfig,
    rendered_files: dict[Path, str],
    *,
    run_command: Any = None,
) -> None:
    """Apply the rendered install plan to live system paths."""
    runner = run_command or run_privileged_command
    _write_tree(rendered_files, source_root=config.systemd_dir, destination_root=config.live_systemd_dir, run_command=runner)
    if config.nginx_conf_path is not None and config.live_nginx_conf_path is not None:
        nginx_content = rendered_files.get(config.nginx_conf_path)
        if nginx_content is None and config.nginx_conf_path.is_file():
            nginx_content = config.nginx_conf_path.read_text(encoding="utf-8")
        if nginx_content is None:
            raise FileNotFoundError(f"Rendered nginx config missing at `{config.nginx_conf_path}`.")
        _write_file(config.live_nginx_conf_path, nginx_content, run_command=runner)
        if config.live_nginx_enabled_path is not None:
            _ensure_symlink(config.live_nginx_enabled_path, config.live_nginx_conf_path, run_command=runner)
    if config.acme_root is not None:
        runner(["mkdir", "-p", str(config.acme_root)])
    runner(["systemctl", "daemon-reload"])
    runner(["systemctl", "enable", "maverick-core.service"])
    runner(["systemctl", "enable", "maverick-rescue.service"])
    runner(["systemctl", "enable", "maverick-backend-watchdog.timer"])
    runner(["systemctl", "restart", "maverick-core.service"])
    runner(["systemctl", "restart", "maverick-rescue.service"])
    runner(["systemctl", "start", "maverick-backend-watchdog.timer"])
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
    if config.live_nginx_conf_path is not None:
        _write_file(config.live_nginx_conf_path, render_nginx_config(config, force_https=True), run_command=runner)
        if config.live_nginx_enabled_path is not None:
            _ensure_symlink(config.live_nginx_enabled_path, config.live_nginx_conf_path, run_command=runner)
    runner(["nginx", "-t"])
    runner(["systemctl", "reload", "nginx"])


def check_health(
    config: InstallerConfig,
    *,
    timeout_seconds: float = 5.0,
    attempts: int = 8,
    delay_seconds: float = 2.0,
    sleep_func: Any = time.sleep,
) -> dict[str, bool]:
    """Return local/public health availability after install."""
    urls = [f"http://{config.bind_host}:{config.core_port}/health"]
    if not config.local_only and config.hostname:
        urls.append(f"{config.public_scheme}://{config.hostname}/health")
    return {
        url: _url_becomes_healthy(
            url,
            timeout_seconds=timeout_seconds,
            attempts=attempts,
            delay_seconds=delay_seconds,
            sleep_func=sleep_func,
        )
        for url in urls
    }


def default_output_root(repository_root: Path) -> Path:
    """Return the default installer output root inside the repository."""
    return repository_root / ".maverick" / "install"


def default_systemd_dir(output_root: Path) -> Path:
    """Return the default systemd rendering directory."""
    return output_root / "systemd"


def default_install_env_path(install_root: Path) -> Path:
    """Return the service environment file path for one install root."""
    return install_root / ".env.maverick"


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


def _template_substitutions(config: InstallerConfig) -> dict[str, str]:
    return {
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
        "{{ENV_FILE}}": str(config.install_env_path),
    }


def _tls_certificate_files_exist(config: InstallerConfig) -> bool:
    if config.public_scheme != "https" or not config.hostname:
        return False
    try:
        return Path(config.tls_certificate_path).is_file() and Path(config.tls_certificate_key_path).is_file()
    except OSError:
        return False


def _read_env_file(path: Path) -> dict[str, str]:
    return read_env_file(path)


def _quote_env_value(value: str) -> str:
    return quote_env_value(value)


def _unquote_env_value(value: str) -> str:
    return unquote_env_value(value)


def run_privileged_command(command: list[str]) -> None:
    """Run one installer command, adding sudo when required."""
    if os.geteuid() == 0:
        subprocess.run(command, check=True)
        return
    subprocess.run(["sudo", *command], check=True)


def _write_tree(files: dict[Path, str], *, source_root: Path, destination_root: Path, run_command: Any = None) -> None:
    for source_path, content in files.items():
        if not _is_relative_to(source_path, source_root):
            continue
        target_path = destination_root / source_path.relative_to(source_root)
        _write_file(target_path, content, run_command=run_command)


def _write_file(path: Path, content: str, *, run_command: Any = None, mode: str = "0644") -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except PermissionError:
        runner = run_command or run_privileged_command
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
                temporary_path = Path(handle.name)
                handle.write(content)
            runner(["install", "-D", "-m", mode, str(temporary_path), str(path)])
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()


def _ensure_symlink(link_path: Path, target_path: Path, *, run_command: Any = None) -> None:
    if _same_path(link_path, target_path):
        return
    try:
        link_path.parent.mkdir(parents=True, exist_ok=True)
        if link_path.is_symlink() or link_path.exists():
            link_path.unlink()
        link_path.symlink_to(target_path)
    except PermissionError:
        runner = run_command or run_privileged_command
        runner(["mkdir", "-p", str(link_path.parent)])
        runner(["ln", "-sfn", str(target_path), str(link_path)])


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve(strict=False) == right.resolve(strict=False)
    except OSError:
        return str(left) == str(right)


def _url_is_healthy(url: str, *, timeout_seconds: float) -> bool:
    try:
        with request.urlopen(url, timeout=timeout_seconds) as response:
            return 200 <= response.status < 300
    except (error.URLError, TimeoutError, ValueError):
        return False


def _url_becomes_healthy(
    url: str,
    *,
    timeout_seconds: float,
    attempts: int,
    delay_seconds: float,
    sleep_func: Any,
) -> bool:
    total_attempts = max(1, attempts)
    for attempt in range(total_attempts):
        if _url_is_healthy(url, timeout_seconds=timeout_seconds):
            return True
        if attempt < total_attempts - 1 and delay_seconds > 0:
            sleep_func(delay_seconds)
    return False


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
