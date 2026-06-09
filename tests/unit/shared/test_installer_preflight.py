"""Tests for installer preflight dependency checks."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import patch

from core.shared.installer import (
    InstallerConfig,
    default_install_env_path,
    default_output_root,
    default_systemd_dir,
    preflight_check,
)


class InstallerPreflightTestCase(unittest.TestCase):
    def test_preflight_requires_supported_node_when_building_frontends(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        config = replace(_make_config(repo_root), build_frontends=True)

        with patch("core.shared.installer.node_runtime_diagnostic", return_value="node 20.18.1 is too old"), patch(
            "core.shared.installer.shutil.which",
            return_value="/usr/bin/tool",
        ):
            report = preflight_check(config, live_apply=False, request_tls=False)

        self.assertIn("node 20.18.1 is too old", report.errors)


def _make_config(repo_root: Path) -> InstallerConfig:
    output_root = default_output_root(repo_root)
    return InstallerConfig(
        repository_root=repo_root,
        install_root=repo_root,
        output_root=output_root,
        service_user="ubuntu",
        service_group="ubuntu",
        bind_host="127.0.0.1",
        hostname=None,
        public_scheme="http",
        core_port=8014,
        rescue_port=8015,
        bootstrap=False,
        verify=False,
        local_only=True,
        acme_root=None,
        systemd_dir=default_systemd_dir(output_root),
        nginx_conf_path=None,
        install_env_path=default_install_env_path(repo_root),
        live_systemd_dir=Path("/etc/systemd/system"),
        live_nginx_conf_path=None,
        live_nginx_enabled_path=None,
        build_frontends=False,
    )


if __name__ == "__main__":
    unittest.main()
