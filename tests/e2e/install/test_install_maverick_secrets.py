"""Installer tests for bootstrap secret material."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from core.secrets.bootstrap import resolve_bootstrap_secret
from core.shared.installer import (
    DEFAULT_MONGODB_PASSWORD_REF,
    InstallerConfig,
    default_install_env_path,
    default_live_systemd_dir,
    default_systemd_dir,
    render_install_plan,
    write_install_plan,
)


class InstallerSecretRenderingTestCase(unittest.TestCase):
    def make_config(self, repo_root: Path, *, install_root: Path) -> InstallerConfig:
        output_root = install_root / "install"
        return InstallerConfig(
            repository_root=repo_root,
            install_root=install_root,
            output_root=output_root,
            service_user="ubuntu",
            service_group="ubuntu",
            bind_host="127.0.0.1",
            hostname=None,
            public_scheme="https",
            core_port=8014,
            rescue_port=8015,
            bootstrap=False,
            verify=False,
            local_only=True,
            acme_root=None,
            systemd_dir=default_systemd_dir(output_root),
            nginx_conf_path=None,
            install_env_path=default_install_env_path(install_root),
            live_systemd_dir=default_live_systemd_dir(),
            live_nginx_conf_path=None,
            live_nginx_enabled_path=None,
            build_frontends=False,
        )

    def test_render_install_plan_stores_mongo_password_as_bootstrap_secret_ref(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory(prefix="maverick-install-") as temp_dir:
            install_root = Path(temp_dir)
            config = replace(
                self.make_config(repo_root, install_root=install_root),
                control_store="mongo",
                mongodb_username="maverick-user",
                mongodb_password_ref=DEFAULT_MONGODB_PASSWORD_REF,
                mongodb_password="super-secret-mongo-password",
                secret_key_file="bootstrap-secrets/secret-store.key",
                bootstrap_secret_store_root="bootstrap-secrets",
            )

            rendered = render_install_plan(config)
            write_install_plan(rendered)
            env_file = (install_root / ".env.maverick").read_text(encoding="utf-8")

            self.assertIn("MAVERICK_MONGODB_USERNAME=maverick-user", env_file)
            self.assertIn(f"MAVERICK_MONGODB_PASSWORD_REF={DEFAULT_MONGODB_PASSWORD_REF}", env_file)
            self.assertNotIn("super-secret-mongo-password", env_file)
            self.assertNotIn("MAVERICK_MONGODB_PASSWORD=", env_file)
            self.assertNotIn(
                "super-secret-mongo-password",
                (install_root / "bootstrap-secrets" / "values.json").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                resolve_bootstrap_secret(
                    DEFAULT_MONGODB_PASSWORD_REF,
                    repository_root=install_root,
                    environment={
                        "MAVERICK_BOOTSTRAP_SECRET_STORE_ROOT": "bootstrap-secrets",
                        "MAVERICK_SECRET_KEY_FILE": str(install_root / "bootstrap-secrets" / "secret-store.key"),
                    },
                ),
                "super-secret-mongo-password",
            )


if __name__ == "__main__":
    unittest.main()
