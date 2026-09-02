#!/usr/bin/env python3
"""Interactive CLI installer for Maverick."""

from __future__ import annotations

import argparse
from dataclasses import fields
import getpass
import grp
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from urllib.parse import urlparse

if sys.version_info < (3, 12):
    sys.stderr.write(
        "Maverick installer requires Python 3.12 or newer.\n\n"
        "Run it with Python 3.12 explicitly, for example:\n"
        "  python3.12 scripts/install_maverick.py\n\n"
        "After local bootstrap, you can also use:\n"
        "  .venv/bin/python scripts/install_maverick.py\n"
    )
    raise SystemExit(1)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from core.shared.installer import (  # noqa: E402
    DEFAULT_MONGODB_PASSWORD_REF,
    InstallerConfig,
    apply_initial_admin_password,
    apply_install_plan,
    check_health,
    default_install_env_path,
    default_install_root,
    default_live_nginx_conf_path,
    default_live_nginx_enabled_path,
    default_live_systemd_dir,
    default_nginx_conf_path,
    default_output_root,
    default_systemd_dir,
    preflight_check,
    render_install_plan,
    request_tls_certificate,
    run_privileged_command,
    run_install_steps,
    write_install_plan,
)

INTERNAL_APPLY_ADMIN_PASSWORD_FLAG = "--_apply-initial-admin-password-from-stdin"
TLS_FAILED_EXIT_CODE = 4
LIVE_APPLY_FAILED_EXIT_CODE = 5
CONFIG_PATH_FIELDS = {
    "repository_root",
    "install_root",
    "output_root",
    "acme_root",
    "systemd_dir",
    "nginx_conf_path",
    "install_env_path",
    "live_systemd_dir",
    "live_nginx_conf_path",
    "live_nginx_enabled_path",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hostname", help="Public hostname for nginx/TLS, for example maverick.<host>.com.")
    parser.add_argument("--public-scheme", default="https", choices=("http", "https"))
    parser.add_argument("--local-only", action="store_true", help="Skip nginx/TLS and keep the install local-only.")
    parser.add_argument("--install-root", type=Path, default=default_install_root(Path(__file__)))
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--systemd-dir", type=Path, default=None, help="Render-only systemd output path.")
    parser.add_argument("--nginx-conf", type=Path, default=None, help="Render-only nginx config output path.")
    parser.add_argument("--install-env", type=Path, default=None, help="Rendered service environment file path.")
    parser.add_argument("--live-systemd-dir", type=Path, default=default_live_systemd_dir())
    parser.add_argument("--live-nginx-conf", type=Path, default=None, help="Live nginx config path for apply.")
    parser.add_argument("--live-nginx-enabled", type=Path, default=None, help="Live nginx symlink path for apply.")
    parser.add_argument("--acme-root", type=Path, default=None, help="ACME webroot used in rendered nginx config.")
    parser.add_argument("--service-user", default=os.environ.get("USER") or "ubuntu")
    parser.add_argument("--service-group", default=_default_group_name())
    parser.add_argument("--bind-host", default="127.0.0.1")
    parser.add_argument("--core-port", type=int, default=8014)
    parser.add_argument("--rescue-port", type=int, default=8015)
    parser.add_argument("--control-store", choices=("json", "mongo"), default="json")
    parser.add_argument("--json-control-store-root", default="data/control-plane/json")
    parser.add_argument("--mongodb-uri", default="mongodb://127.0.0.1:27017/maverick")
    parser.add_argument("--mongodb-database", default="maverick")
    parser.add_argument("--mongodb-username", default="")
    parser.add_argument(
        "--mongodb-password-ref",
        default="",
        help="Existing bootstrap secret ref for MongoDB password. Interactive installs usually ask for the password instead.",
    )
    parser.add_argument(
        "--admin-password-file",
        type=Path,
        default=None,
        help="Read the initial admin password from a local file for non-interactive live installs.",
    )
    parser.add_argument("--secret-key-file", default="data/bootstrap-secrets/secret-store.key")
    parser.add_argument("--bootstrap-secret-store-root", default="data/bootstrap-secrets")
    parser.add_argument("--skip-bootstrap", action="store_true")
    parser.add_argument("--skip-verify", action="store_true")
    parser.add_argument("--build-frontends", action="store_true", help="Build app frontends during bootstrap.")
    parser.add_argument("--skip-tls", action="store_true", help="Skip the TLS certbot step.")
    parser.add_argument(
        "--hosted-sidecars",
        action="store_true",
        help="Enable isolated hosted sidecar and app-frame origins.",
    )
    parser.add_argument(
        "--browser-origin-tls-mode",
        choices=("external_wildcard", "managed_exact"),
        default="external_wildcard",
        help="Use external DNS-01 wildcard TLS or Core-managed exact HTTP-01 certificates.",
    )
    parser.add_argument(
        "--sidecar-tls-cert",
        default="",
        help="Wildcard sidecar certificate path (defaults to the Certbot <hostname>-sidecars lineage).",
    )
    parser.add_argument(
        "--sidecar-tls-key",
        default="",
        help="Wildcard sidecar private-key path (defaults to the Certbot <hostname>-sidecars lineage).",
    )
    parser.add_argument(
        "--browser-origin-tls-root",
        default="",
        help="Private/published certificate root for managed_exact mode.",
    )
    parser.add_argument(
        "--browser-origin-acme-webroot",
        default="",
        help="HTTP-01 webroot for managed_exact mode.",
    )
    parser.add_argument(
        "--browser-origin-acme-ca",
        default="",
        help="Optional ACME directory override for managed_exact mode.",
    )
    parser.add_argument(
        "--browser-origin-tls-nginx-group",
        default="www-data",
        help="Nginx worker group allowed to read published managed keys.",
    )
    parser.add_argument("--skip-health-check", action="store_true", help="Skip final post-apply health checks.")
    parser.add_argument("--render-only", action="store_true", help="Only render files, do not offer live apply.")
    parser.add_argument("--force", action="store_true", help="Continue despite blocking preflight errors.")
    parser.add_argument("--yes", action="store_true", help="Accept prompts and apply defaults non-interactively.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    tokens = list(sys.argv[1:] if argv is None else argv)
    if tokens == [INTERNAL_APPLY_ADMIN_PASSWORD_FLAG]:
        return _apply_initial_admin_password_from_stdin()

    args = parse_args(tokens)
    interactive = not args.yes
    config = build_config(args, interactive=interactive)

    _print_plan(config)
    request_tls = not args.skip_tls and not config.local_only and config.public_scheme == "https" and config.hostname is not None
    preflight = preflight_check(config, live_apply=not args.render_only, request_tls=request_tls)
    _print_preflight(preflight.errors, preflight.warnings)
    if preflight.errors and not args.force:
        print("Preflight failed. Re-run with --force only if an operator has prepared equivalent dependencies.")
        return 2

    run_install_steps(config)
    force_https_nginx = args.skip_tls and not config.local_only and config.public_scheme == "https"
    rendered = render_install_plan(config, force_https_nginx=force_https_nginx)
    write_install_plan(rendered)
    print(f"Rendered install plan under {config.output_root}.")

    if args.render_only:
        _print_summary(config, live_applied=False, tls_status="not requested")
        return 0

    apply_changes = args.yes or _confirm(
        "Apply the rendered plan to live systemd/nginx paths and start services now?",
        default=True,
    )
    if not apply_changes:
        print("Skipped live apply. Services were not installed, nginx was not updated, and TLS was not requested.")
        _print_summary(config, live_applied=False, tls_status="not requested")
        return 0

    _prepare_mongodb(config, assume_yes=args.yes)
    _apply_initial_admin_password(config)
    try:
        apply_install_plan(config, rendered)
    except subprocess.CalledProcessError as exc:
        print(f"Live install apply failed with exit code {exc.returncode}.")
        print("Rendered files were written, but systemd/nginx may be partially updated. Fix the reported command error and re-run the installer.")
        return LIVE_APPLY_FAILED_EXIT_CODE

    tls_status = "not requested"
    should_request_tls = (
        not args.skip_tls
        and not config.local_only
        and config.public_scheme == "https"
        and config.hostname is not None
        and (args.yes or _confirm("Request a TLS certificate with certbot now?", default=True))
    )
    if should_request_tls:
        try:
            request_tls_certificate(config)
        except subprocess.CalledProcessError as exc:
            tls_status = "failed"
            print(f"TLS certificate request failed with exit code {exc.returncode}.")
            print("Live services and nginx were applied. Fix certbot/DNS/port 80/443, then re-run the installer or run certbot manually.")
        else:
            tls_status = "requested"

    if tls_status == "failed":
        _print_summary(config, live_applied=True, tls_status=tls_status)
        return TLS_FAILED_EXIT_CODE

    if not args.skip_health_check:
        health = check_health(config)
        _print_health(health)
        if not all(health.values()):
            print("Install applied, but at least one required health check failed.")
            _print_summary(config, live_applied=True, tls_status=tls_status)
            return 3

    _print_summary(config, live_applied=True, tls_status=tls_status)
    return 0


def _apply_initial_admin_password(config: InstallerConfig) -> None:
    if not config.admin_password:
        return
    if config.control_store != "mongo" or _running_inside_install_venv(config):
        _ensure_mongo_driver_available(config)
        apply_initial_admin_password(config)
        return
    venv_python = config.repository_root / ".venv" / "bin" / "python"
    if not venv_python.is_file():
        raise RuntimeError(
            "MongoDB installs must apply the initial admin password through the local virtualenv. "
            "Run bootstrap first or rerun the installer without --skip-bootstrap."
        )
    subprocess.run(
        [str(venv_python), str(Path(__file__).resolve()), INTERNAL_APPLY_ADMIN_PASSWORD_FLAG],
        input=json.dumps(_config_to_payload(config)),
        text=True,
        check=True,
    )


def _apply_initial_admin_password_from_stdin() -> int:
    payload = json.loads(sys.stdin.read())
    config = _config_from_payload(payload)
    _ensure_mongo_driver_available(config)
    apply_initial_admin_password(config)
    return 0


def _ensure_mongo_driver_available(config: InstallerConfig) -> None:
    if config.control_store != "mongo" or importlib.util.find_spec("pymongo") is not None:
        return
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", ".[mongo]"],
        cwd=config.repository_root,
        check=True,
    )


def _prepare_mongodb(config: InstallerConfig, *, assume_yes: bool) -> None:
    if config.control_store != "mongo":
        return
    endpoint = _mongodb_endpoint(config)
    if _mongodb_reachable(endpoint):
        return
    if not _mongodb_endpoint_is_local(endpoint):
        raise SystemExit(
            f"MongoDB is not reachable at {endpoint.host}:{endpoint.port}. "
            "Start the configured MongoDB server or choose the JSON control store."
        )
    if not assume_yes and not _confirm(
        f"MongoDB is not reachable at {endpoint.host}:{endpoint.port}. Install/start local MongoDB now?",
        default=True,
    ):
        raise SystemExit("MongoDB is required when Control store is mongo.")
    _install_or_start_local_mongodb()
    if not _mongodb_becomes_reachable(endpoint):
        raise SystemExit(
            f"MongoDB is still not reachable at {endpoint.host}:{endpoint.port} after install/start. "
            "Check `systemctl status mongod`."
        )


def _install_or_start_local_mongodb() -> None:
    if _start_mongodb_service():
        return
    if shutil.which("apt-get") is None:
        raise SystemExit("Automatic MongoDB install currently requires apt-get. Install MongoDB manually or choose JSON.")
    if _apt_package_available("mongodb-org"):
        _install_mongodb_package()
    else:
        _configure_mongodb_apt_repository()
        _install_mongodb_package()
    if not _start_mongodb_service():
        raise SystemExit("MongoDB was installed, but the mongod service did not start.")


def _start_mongodb_service() -> bool:
    if shutil.which("systemctl") is None:
        return False
    for service_name in ("mongod", "mongodb"):
        if _run_privileged_command_no_check(["systemctl", "start", service_name]):
            return True
    return False


def _apt_package_available(package: str) -> bool:
    if shutil.which("apt-cache") is None:
        return False
    return subprocess.run(["apt-cache", "show", package], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def _install_mongodb_package() -> None:
    run_privileged_command(["apt-get", "update"])
    run_privileged_command(["apt-get", "install", "-y", "mongodb-org"])


def _configure_mongodb_apt_repository() -> None:
    repo_line = _mongodb_apt_repository_line()
    run_privileged_command(["apt-get", "update"])
    run_privileged_command(["apt-get", "install", "-y", "curl", "gnupg"])
    run_privileged_command(
        [
            "bash",
            "-lc",
            "curl -fsSL https://www.mongodb.org/static/pgp/server-8.0.asc "
            "| gpg --dearmor --yes "
            "| tee /usr/share/keyrings/mongodb-server-8.0.gpg >/dev/null",
        ]
    )
    run_privileged_command(
        [
            "bash",
            "-lc",
            f"printf '%s\\n' {json.dumps(repo_line)} "
            "> /etc/apt/sources.list.d/mongodb-org-8.0.list",
        ]
    )


def _mongodb_apt_repository_line() -> str:
    os_release = _read_os_release()
    os_id = os_release.get("ID", "")
    codename = os_release.get("VERSION_CODENAME", "")
    arch_clause = "arch=amd64,arm64 "
    if os_id == "ubuntu" and codename in {"focal", "jammy", "noble"}:
        return (
            f"deb [ {arch_clause}signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] "
            f"https://repo.mongodb.org/apt/ubuntu {codename}/mongodb-org/8.0 multiverse"
        )
    if os_id == "debian" and codename in {"bullseye", "bookworm"}:
        return (
            "deb [ signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] "
            f"https://repo.mongodb.org/apt/debian {codename}/mongodb-org/8.0 main"
        )
    raise SystemExit(
        "Automatic MongoDB install supports Ubuntu focal/jammy/noble and Debian bullseye/bookworm. "
        "Install MongoDB manually or choose JSON."
    )


def _read_os_release(path: Path = Path("/etc/os-release")) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        values[key] = value.strip().strip('"')
    return values


def _run_privileged_command_no_check(command: list[str]) -> bool:
    try:
        run_privileged_command(command)
    except subprocess.CalledProcessError:
        return False
    return True


class _MongoEndpoint:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port


def _mongodb_endpoint(config: InstallerConfig) -> _MongoEndpoint:
    parsed = urlparse(config.mongodb_uri)
    netloc = parsed.netloc.split(",", 1)[0]
    if "@" in netloc:
        netloc = netloc.rsplit("@", 1)[1]
    if netloc.startswith("["):
        host, _, tail = netloc[1:].partition("]")
        port = int(tail.removeprefix(":") or "27017")
        return _MongoEndpoint(host=host, port=port)
    host, _, port_text = netloc.partition(":")
    return _MongoEndpoint(host=host or "127.0.0.1", port=int(port_text or "27017"))


def _mongodb_endpoint_is_local(endpoint: _MongoEndpoint) -> bool:
    return endpoint.host in {"localhost", "127.0.0.1", "::1"}


def _mongodb_reachable(endpoint: _MongoEndpoint, *, timeout_seconds: float = 1.0) -> bool:
    try:
        with socket.create_connection((endpoint.host, endpoint.port), timeout=timeout_seconds):
            return True
    except OSError:
        return False


def _mongodb_becomes_reachable(endpoint: _MongoEndpoint) -> bool:
    for _ in range(10):
        if _mongodb_reachable(endpoint):
            return True
        time.sleep(1)
    return False


def _running_inside_install_venv(config: InstallerConfig) -> bool:
    try:
        return Path(sys.prefix).resolve() == (config.repository_root / ".venv").resolve()
    except OSError:
        return False


def _config_to_payload(config: InstallerConfig) -> dict[str, object]:
    payload: dict[str, object] = {}
    for item in fields(InstallerConfig):
        value = getattr(config, item.name)
        if item.name in CONFIG_PATH_FIELDS:
            payload[item.name] = None if value is None else str(value)
        else:
            payload[item.name] = value
    return payload


def _config_from_payload(payload: dict[str, object]) -> InstallerConfig:
    values = dict(payload)
    for key in CONFIG_PATH_FIELDS:
        if values.get(key) is not None:
            values[key] = Path(str(values[key]))
    return InstallerConfig(**values)


def build_config(args: argparse.Namespace, *, interactive: bool) -> InstallerConfig:
    repository_root = default_install_root(Path(__file__))
    local_only = bool(args.local_only)
    hostname = _normalize_hostname(args.hostname)
    if interactive and not local_only and hostname is None:
        local_only, hostname = _prompt_install_mode(default_hostname=None)
    elif not local_only and hostname is None:
        raise SystemExit("--hostname is required unless --local-only is set.")
    elif interactive:
        local_only, hostname = _prompt_install_mode(default_hostname=hostname, default_local_only=local_only)

    install_root = _prompt_path("Install root", args.install_root.resolve(), interactive=interactive)
    if install_root != repository_root:
        raise SystemExit(
            "--install-root must currently match the checkout root. "
            "Clone Maverick directly into the intended install root, or use --install-root "
            f"{repository_root}."
        )
    service_user = _prompt_text("Service user", args.service_user, interactive=interactive)
    service_group = _prompt_text("Service group", args.service_group, interactive=interactive)
    bind_host = _prompt_text("Core bind host", args.bind_host, interactive=interactive)
    core_port = _prompt_int("Core port", args.core_port, interactive=interactive)
    rescue_port = _prompt_int("Rescue port", args.rescue_port, interactive=interactive)
    control_store = _prompt_choice(
        "Control store",
        default=args.control_store,
        choices=("json", "mongo"),
        interactive=interactive,
    )
    admin_password = _resolve_admin_password(args, interactive=interactive)
    json_control_store_root = args.json_control_store_root
    mongodb_uri = args.mongodb_uri
    mongodb_database = args.mongodb_database
    mongodb_username = args.mongodb_username
    mongodb_password_ref = args.mongodb_password_ref
    mongodb_password = ""
    if interactive and control_store == "json":
        json_control_store_root = _prompt_text(
            "JSON control store root",
            json_control_store_root,
            interactive=interactive,
        )
    if interactive and control_store == "mongo":
        mongodb_uri = _prompt_text("MongoDB URI", mongodb_uri, interactive=interactive)
        mongodb_database = _prompt_text("MongoDB database", mongodb_database, interactive=interactive)
        mongodb_username = _prompt_optional_text("MongoDB username", mongodb_username, interactive=interactive)
        mongodb_password = _prompt_password("MongoDB password", interactive=interactive) if mongodb_username else ""
        if mongodb_password and not mongodb_password_ref:
            mongodb_password_ref = DEFAULT_MONGODB_PASSWORD_REF
        if mongodb_username and not (mongodb_password or mongodb_password_ref):
            raise SystemExit("MongoDB password is required when MongoDB username is set.")
    public_scheme = args.public_scheme if local_only else _prompt_choice(
        "Public scheme",
        default=args.public_scheme,
        choices=("https", "http"),
        interactive=interactive,
    )

    output_root = (args.output_root or default_output_root(repository_root)).resolve()
    systemd_dir = (args.systemd_dir or default_systemd_dir(output_root)).resolve()
    install_env_path = (args.install_env or default_install_env_path(install_root)).resolve()
    nginx_conf_path = None if local_only else (args.nginx_conf or default_nginx_conf_path(output_root, hostname=hostname)).resolve()
    acme_root = None if local_only else (args.acme_root or Path("/var/www") / hostname).resolve()
    live_nginx_conf_path = None if local_only else (args.live_nginx_conf or default_live_nginx_conf_path(hostname=hostname)).resolve()
    live_nginx_enabled_path = None if local_only else (args.live_nginx_enabled or default_live_nginx_enabled_path(hostname=hostname)).resolve()

    return InstallerConfig(
        repository_root=repository_root,
        install_root=install_root,
        output_root=output_root,
        service_user=service_user,
        service_group=service_group,
        bind_host=bind_host,
        hostname=hostname,
        public_scheme=public_scheme,
        core_port=core_port,
        rescue_port=rescue_port,
        bootstrap=not args.skip_bootstrap,
        verify=not args.skip_verify,
        local_only=local_only,
        acme_root=acme_root,
        systemd_dir=systemd_dir,
        nginx_conf_path=nginx_conf_path,
        install_env_path=install_env_path,
        live_systemd_dir=args.live_systemd_dir.resolve(),
        live_nginx_conf_path=live_nginx_conf_path,
        live_nginx_enabled_path=live_nginx_enabled_path,
        build_frontends=bool(args.build_frontends),
        control_store=control_store,
        json_control_store_root=json_control_store_root,
        mongodb_uri=mongodb_uri,
        mongodb_database=mongodb_database,
        mongodb_username=mongodb_username,
        mongodb_password_ref=mongodb_password_ref,
        mongodb_password=mongodb_password,
        admin_password=admin_password,
        secret_key_file=args.secret_key_file,
        bootstrap_secret_store_root=args.bootstrap_secret_store_root,
        hosted_sidecars=bool(args.hosted_sidecars),
        sidecar_tls_cert_path=str(args.sidecar_tls_cert or "").strip(),
        sidecar_tls_key_path=str(args.sidecar_tls_key or "").strip(),
        browser_origin_tls_mode=str(args.browser_origin_tls_mode).strip(),
        browser_origin_tls_root=str(args.browser_origin_tls_root or "").strip(),
        browser_origin_acme_webroot=str(args.browser_origin_acme_webroot or "").strip(),
        browser_origin_acme_ca=str(args.browser_origin_acme_ca or "").strip(),
        browser_origin_tls_nginx_group=str(args.browser_origin_tls_nginx_group or "").strip(),
    )


def _normalize_hostname(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    return normalized or None


def _default_group_name() -> str:
    try:
        return grp.getgrgid(os.getgid()).gr_name
    except KeyError:
        return os.environ.get("USER") or "ubuntu"


def _prompt_install_mode(
    default_hostname: str | None,
    *,
    default_local_only: bool = False,
) -> tuple[bool, str | None]:
    mode = _prompt_choice(
        "Install mode",
        choices=("public", "local-only"),
        default="local-only" if default_local_only else "public",
        interactive=True,
    )
    if mode == "local-only":
        return True, None
    hostname = _prompt_text("Public hostname", default_hostname or "", interactive=True)
    normalized = _normalize_hostname(hostname)
    if not normalized:
        raise SystemExit("A public install requires a hostname.")
    return False, normalized


def _prompt_text(label: str, default: str, *, interactive: bool) -> str:
    if not interactive:
        return default
    raw = input(f"{label} [{default}]: ").strip()
    return raw or default


def _prompt_optional_text(label: str, default: str, *, interactive: bool) -> str:
    if not interactive:
        return default
    suffix = f" [{default}]" if default else " [empty for none]"
    raw = input(f"{label}{suffix}: ").strip()
    return raw or default


def _prompt_password(label: str, *, interactive: bool) -> str:
    if not interactive:
        return ""
    return getpass.getpass(f"{label} [empty for none]: ").strip()


def _resolve_admin_password(args: argparse.Namespace, *, interactive: bool) -> str:
    if args.admin_password_file is not None:
        password = args.admin_password_file.read_text(encoding="utf-8").strip()
        _validate_admin_password(password, label="Admin password file")
        return password
    if interactive:
        return _prompt_new_password("Admin password", required=not args.render_only)
    if args.render_only:
        return ""
    raise SystemExit("--admin-password-file is required for non-interactive live installs.")


def _prompt_new_password(label: str, *, required: bool) -> str:
    password = getpass.getpass(f"{label}: ").strip()
    if not password:
        if required:
            raise SystemExit(f"{label} is required.")
        return ""
    _validate_admin_password(password, label=label)
    confirmation = getpass.getpass(f"Confirm {label}: ").strip()
    if password != confirmation:
        raise SystemExit(f"{label} confirmation did not match.")
    return password


def _validate_admin_password(password: str, *, label: str) -> None:
    if len(password) < 8:
        raise SystemExit(f"{label} must be at least 8 characters.")


def _prompt_path(label: str, default: Path, *, interactive: bool) -> Path:
    value = _prompt_text(label, str(default), interactive=interactive)
    return Path(value).expanduser().resolve()


def _prompt_int(label: str, default: int, *, interactive: bool) -> int:
    if not interactive:
        return default
    raw = input(f"{label} [{default}]: ").strip()
    if not raw:
        return default
    return int(raw)


def _prompt_choice(label: str, *, choices: tuple[str, ...], default: str, interactive: bool) -> str:
    if not interactive:
        return default
    prompt = "/".join(choices)
    raw = input(f"{label} [{default}] ({prompt}): ").strip().lower()
    if not raw:
        return default
    if raw not in choices:
        raise SystemExit(f"Invalid value for {label}: {raw}")
    return raw


def _confirm(prompt: str, *, default: bool) -> bool:
    suffix = "Y/n" if default else "y/N"
    raw = input(f"{prompt} [{suffix}]: ").strip().lower()
    if not raw:
        return default
    return raw in {"y", "yes"}


def _print_plan(config: InstallerConfig) -> None:
    print("Maverick installer plan")
    print(f"- Repository root: {config.repository_root}")
    print(f"- Install root: {config.install_root}")
    print(f"- Public URL: {config.public_url}")
    print(f"- Service user/group: {config.service_user}:{config.service_group}")
    print(f"- Core bind: {config.bind_host}:{config.core_port}")
    print(f"- Rescue bind: {config.bind_host}:{config.rescue_port}")
    print(f"- Control store: {config.control_store}")
    if config.hosted_sidecars:
        print(f"- Browser-origin TLS: {config.browser_origin_tls_mode}")
    print(f"- Rendered systemd dir: {config.systemd_dir}")
    print(f"- Service env file: {config.install_env_path}")
    if config.nginx_conf_path is not None:
        print(f"- Rendered nginx config: {config.nginx_conf_path}")
    print(f"- Live systemd dir: {config.live_systemd_dir}")
    if config.live_nginx_conf_path is not None:
        print(f"- Live nginx config: {config.live_nginx_conf_path}")


def _print_preflight(errors: list[str], warnings: list[str]) -> None:
    if not errors and not warnings:
        print("Preflight checks passed.")
        return
    if errors:
        print("Preflight errors:")
        for item in errors:
            print(f"- {item}")
    if warnings:
        print("Preflight warnings:")
        for warning in warnings:
            print(f"- {warning}")


def _print_health(results: dict[str, bool]) -> None:
    print("Health checks:")
    for url, ok in results.items():
        status = "OK" if ok else "FAILED"
        print(f"- {url}: {status}")


def _print_summary(config: InstallerConfig, *, live_applied: bool, tls_status: str) -> None:
    if live_applied:
        print("Maverick live install flow complete.")
    else:
        print("Maverick render flow complete. Live services were not changed.")
    print(f"Rendered files: {config.output_root}")
    print(f"Public URL: {config.public_url}")
    if live_applied and config.public_scheme == "https" and not config.local_only:
        print(f"TLS certificate: {tls_status}")
    print("Admin login:")
    print("  Username: admin")
    if config.admin_password:
        print("  Password: configured during install")
    else:
        print("  Password: not applied in render-only mode")


if __name__ == "__main__":
    raise SystemExit(main())
