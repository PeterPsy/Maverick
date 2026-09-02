"""Shared configuration fixture for installer end-to-end tests."""

from __future__ import annotations

from pathlib import Path

from core.shared.installer import (
    InstallerConfig,
    default_install_env_path,
    default_live_nginx_conf_path,
    default_live_nginx_enabled_path,
    default_live_systemd_dir,
    default_nginx_conf_path,
    default_output_root,
    default_systemd_dir,
)


def make_installer_config(
    repo_root: Path,
    *,
    hostname: str | None,
    local_only: bool,
) -> InstallerConfig:
    """Build the common deterministic installer rendering fixture."""
    output_root = default_output_root(repo_root)
    return InstallerConfig(
        repository_root=repo_root,
        install_root=repo_root,
        output_root=output_root,
        service_user="ubuntu",
        service_group="ubuntu",
        bind_host="127.0.0.1",
        hostname=hostname,
        public_scheme="https",
        core_port=8014,
        rescue_port=8015,
        bootstrap=False,
        verify=False,
        local_only=local_only,
        acme_root=None if hostname is None else Path("/var/www") / hostname,
        systemd_dir=default_systemd_dir(output_root),
        nginx_conf_path=(
            None
            if hostname is None
            else default_nginx_conf_path(output_root, hostname=hostname)
        ),
        install_env_path=default_install_env_path(repo_root),
        live_systemd_dir=default_live_systemd_dir(),
        live_nginx_conf_path=(
            None if hostname is None else default_live_nginx_conf_path(hostname=hostname)
        ),
        live_nginx_enabled_path=(
            None
            if hostname is None
            else default_live_nginx_enabled_path(hostname=hostname)
        ),
        build_frontends=False,
    )
