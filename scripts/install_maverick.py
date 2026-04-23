#!/usr/bin/env python3
"""Bootstrap and render one Maverick installation configuration."""

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
    default_install_root,
    default_nginx_conf_path,
    default_output_root,
    default_systemd_dir,
    render_install_plan,
    run_install_steps,
    write_install_plan,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hostname", help="Public hostname for nginx/TLS, for example maverick.example.com.")
    parser.add_argument("--public-scheme", default="https", choices=("http", "https"))
    parser.add_argument("--local-only", action="store_true", help="Skip nginx rendering and keep the install local-only.")
    parser.add_argument("--install-root", type=Path, default=default_install_root(Path(__file__)))
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--systemd-dir", type=Path, default=None)
    parser.add_argument("--nginx-conf", type=Path, default=None, help="Explicit nginx config output path.")
    parser.add_argument("--acme-root", type=Path, default=None, help="ACME webroot used in rendered nginx config.")
    parser.add_argument("--service-user", default=os.environ.get("USER") or "ubuntu")
    parser.add_argument("--service-group", default=_default_group_name())
    parser.add_argument("--bind-host", default="127.0.0.1")
    parser.add_argument("--core-port", type=int, default=8014)
    parser.add_argument("--rescue-port", type=int, default=8015)
    parser.add_argument("--skip-bootstrap", action="store_true")
    parser.add_argument("--skip-verify", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repository_root = default_install_root(Path(__file__))
    output_root = (args.output_root or default_output_root(repository_root)).resolve()
    hostname = None if args.local_only else _normalize_hostname(args.hostname)
    if not args.local_only and not hostname:
        raise SystemExit("--hostname is required unless --local-only is set.")
    systemd_dir = (args.systemd_dir or default_systemd_dir(output_root)).resolve()
    nginx_conf_path = None if args.local_only else (args.nginx_conf or default_nginx_conf_path(output_root, hostname=hostname)).resolve()
    acme_root = None if args.local_only else (args.acme_root or Path("/var/www") / hostname).resolve()
    config = InstallerConfig(
        repository_root=repository_root,
        install_root=args.install_root.resolve(),
        output_root=output_root,
        service_user=args.service_user,
        service_group=args.service_group,
        bind_host=args.bind_host,
        hostname=hostname,
        public_scheme=args.public_scheme,
        core_port=args.core_port,
        rescue_port=args.rescue_port,
        bootstrap=not args.skip_bootstrap,
        verify=not args.skip_verify,
        local_only=bool(args.local_only),
        acme_root=acme_root,
        systemd_dir=systemd_dir,
        nginx_conf_path=nginx_conf_path,
    )
    run_install_steps(config)
    rendered = render_install_plan(config)
    write_install_plan(rendered)
    _print_summary(config)
    return 0


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


def _print_summary(config: InstallerConfig) -> None:
    print("Maverick install plan complete.")
    print(f"Repository root: {config.repository_root}")
    print(f"Install root: {config.install_root}")
    print(f"Public URL: {config.public_url}")
    print(f"Systemd units: {config.systemd_dir}")
    if config.nginx_conf_path is not None:
        print(f"Nginx config: {config.nginx_conf_path}")
        print(f"ACME webroot: {config.acme_root}")
    print(f"Core bind: {config.bind_host}:{config.core_port}")
    print(f"Rescue bind: {config.bind_host}:{config.rescue_port}")


if __name__ == "__main__":
    raise SystemExit(main())
