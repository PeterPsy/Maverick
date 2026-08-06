"""Tests for rendered Maverick systemd service environment."""

from __future__ import annotations

from pathlib import Path
import unittest

from core.shared.installer import (
    InstallerConfig,
    default_install_env_path,
    default_output_root,
    default_systemd_dir,
    render_install_plan,
)


class InstallerSystemdTestCase(unittest.TestCase):
    def test_systemd_services_prefer_local_bin_for_node_runtime(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        config = _make_config(repo_root)

        rendered = render_install_plan(config)

        expected_path = "Environment=PATH=/usr/local/bin:/usr/bin:/bin"
        for service_name in (
            "maverick-core.service",
            "maverick-backend-watchdog.service",
            "maverick-rescue.service",
        ):
            with self.subTest(service_name=service_name):
                self.assertIn(expected_path, rendered[config.systemd_dir / service_name])

    def test_core_is_protected_without_preferentially_targeting_runtime_providers(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        config = _make_config(repo_root)

        rendered = render_install_plan(config)

        core_service = rendered[config.systemd_dir / "maverick-core.service"]
        self.assertIn("OOMScoreAdjust=-500", core_service)


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
