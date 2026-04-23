#!/usr/bin/env python3
"""Interactive CLI installer for Maverick."""

from __future__ import annotations

import argparse
import grp
import os
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from core.shared.installer import (  # noqa: E402
    InstallerConfig,
    apply_install_plan,
    check_health,
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hostname", help="Public hostname for nginx/TLS, for example maverick.example.com.")
    parser.add_argument("--public-scheme", default="https", choices=("http", "https"))
    parser.add_argument("--local-only", action="store_true", help="Skip nginx/TLS and keep the install local-only.")
    parser.add_argument("--install-root", type=Path, default=default_install_root(Path(__file__)))
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--systemd-dir", type=Path, default=None, help="Render-only systemd output path.")
    parser.add_argument("--nginx-conf", type=Path, default=None, help="Render-only nginx config output path.")
    parser.add_argument("--live-systemd-dir", type=Path, default=default_live_systemd_dir())
    parser.add_argument("--live-nginx-conf", type=Path, default=None, help="Live nginx config path for apply.")
    parser.add_argument("--live-nginx-enabled", type=Path, default=None, help="Live nginx symlink path for apply.")
    parser.add_argument("--acme-root", type=Path, default=None, help="ACME webroot used in rendered nginx config.")
    parser.add_argument("--service-user", default=os.environ.get("USER") or "ubuntu")
    parser.add_argument("--service-group", default=_default_group_name())
    parser.add_argument("--bind-host", default="127.0.0.1")
    parser.add_argument("--core-port", type=int, default=8014)
    parser.add_argument("--rescue-port", type=int, default=8015)
    parser.add_argument("--skip-bootstrap", action="store_true")
    parser.add_argument("--skip-verify", action="store_true")
    parser.add_argument("--skip-tls", action="store_true", help="Skip the TLS certbot step.")
    parser.add_argument("--render-only", action="store_true", help="Only render files, do not offer live apply.")
    parser.add_argument("--yes", action="store_true", help="Accept prompts and apply defaults non-interactively.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    interactive = not args.yes
    config = build_config(args, interactive=interactive)

    _print_plan(config)
    warnings = preflight_check(config)
    _print_preflight(warnings)

    run_install_steps(config)
    rendered = render_install_plan(config)
    write_install_plan(rendered)
    print(f"Rendered install plan under {config.output_root}.")

    if args.render_only:
        _print_summary(config)
        return 0

    apply_changes = args.yes or _confirm(
        "Apply the rendered plan to the live system paths and manage services?",
        default=False,
    )
    if not apply_changes:
        print("Skipped live apply. Rendered files are ready under the installer output directory.")
        _print_summary(config)
        return 0

    apply_install_plan(config, rendered)

    request_tls = (
        not args.skip_tls
        and not config.local_only
        and config.public_scheme == "https"
        and config.hostname is not None
        and (args.yes or _confirm("Request a TLS certificate with certbot now?", default=False))
    )
    if request_tls:
        request_tls_certificate(config)

    _print_health(check_health(config))
    _print_summary(config)
    return 0


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
    service_user = _prompt_text("Service user", args.service_user, interactive=interactive)
    service_group = _prompt_text("Service group", args.service_group, interactive=interactive)
    bind_host = _prompt_text("Core bind host", args.bind_host, interactive=interactive)
    core_port = _prompt_int("Core port", args.core_port, interactive=interactive)
    rescue_port = _prompt_int("Rescue port", args.rescue_port, interactive=interactive)
    public_scheme = args.public_scheme if local_only else _prompt_choice(
        "Public scheme",
        default=args.public_scheme,
        choices=("https", "http"),
        interactive=interactive,
    )

    output_root = (args.output_root or default_output_root(repository_root)).resolve()
    systemd_dir = (args.systemd_dir or default_systemd_dir(output_root)).resolve()
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
        live_systemd_dir=args.live_systemd_dir.resolve(),
        live_nginx_conf_path=live_nginx_conf_path,
        live_nginx_enabled_path=live_nginx_enabled_path,
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
    print(f"- Rendered systemd dir: {config.systemd_dir}")
    if config.nginx_conf_path is not None:
        print(f"- Rendered nginx config: {config.nginx_conf_path}")
    print(f"- Live systemd dir: {config.live_systemd_dir}")
    if config.live_nginx_conf_path is not None:
        print(f"- Live nginx config: {config.live_nginx_conf_path}")


def _print_preflight(warnings: list[str]) -> None:
    if not warnings:
        print("Preflight checks passed.")
        return
    print("Preflight warnings:")
    for warning in warnings:
        print(f"- {warning}")


def _print_health(results: dict[str, bool]) -> None:
    print("Health checks:")
    for url, ok in results.items():
        status = "OK" if ok else "FAILED"
        print(f"- {url}: {status}")


def _print_summary(config: InstallerConfig) -> None:
    print("Maverick install flow complete.")
    print(f"Rendered files: {config.output_root}")
    print(f"Public URL: {config.public_url}")


if __name__ == "__main__":
    raise SystemExit(main())
