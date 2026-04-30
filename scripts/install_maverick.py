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
import subprocess
import sys

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
    run_install_steps,
    write_install_plan,
)

INTERNAL_APPLY_ADMIN_PASSWORD_FLAG = "--_apply-initial-admin-password-from-stdin"
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
    rendered = render_install_plan(config)
    write_install_plan(rendered)
    print(f"Rendered install plan under {config.output_root}.")

    if args.render_only:
        _print_summary(config, live_applied=False, tls_requested=False)
        return 0

    apply_changes = args.yes or _confirm(
        "Apply the rendered plan to live systemd/nginx paths and start services now?",
        default=True,
    )
    if not apply_changes:
        print("Skipped live apply. Services were not installed, nginx was not updated, and TLS was not requested.")
        _print_summary(config, live_applied=False, tls_requested=False)
        return 0

    _apply_initial_admin_password(config)
    apply_install_plan(config, rendered)

    tls_requested = False
    should_request_tls = (
        not args.skip_tls
        and not config.local_only
        and config.public_scheme == "https"
        and config.hostname is not None
        and (args.yes or _confirm("Request a TLS certificate with certbot now?", default=True))
    )
    if should_request_tls:
        request_tls_certificate(config)
        tls_requested = True

    if not args.skip_health_check:
        health = check_health(config)
        _print_health(health)
        if not all(health.values()):
            print("Install applied, but at least one required health check failed.")
            _print_summary(config, live_applied=True, tls_requested=tls_requested)
            return 3
    _print_summary(config, live_applied=True, tls_requested=tls_requested)
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
        mongodb_username = _prompt_text("MongoDB username", mongodb_username or "maverick", interactive=interactive)
        mongodb_password = _prompt_password("MongoDB password", interactive=interactive)
        if mongodb_password and not mongodb_password_ref:
            mongodb_password_ref = DEFAULT_MONGODB_PASSWORD_REF
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


def _print_summary(config: InstallerConfig, *, live_applied: bool, tls_requested: bool) -> None:
    if live_applied:
        print("Maverick live install flow complete.")
    else:
        print("Maverick render flow complete. Live services were not changed.")
    print(f"Rendered files: {config.output_root}")
    print(f"Public URL: {config.public_url}")
    if live_applied and config.public_scheme == "https" and not config.local_only:
        print(f"TLS certificate requested: {'yes' if tls_requested else 'no'}")
    print("Admin login:")
    print("  Username: admin")
    if config.admin_password:
        print("  Password: configured during install")
    else:
        print("  Password: not applied in render-only mode")


if __name__ == "__main__":
    raise SystemExit(main())
