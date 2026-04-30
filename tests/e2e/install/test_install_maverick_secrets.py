"""Installer tests for bootstrap secret material."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from core.api.control_store import ControlStoreSettings, build_control_plane_collections
from core.identity.service import authenticate_password
from core.identity.store import IdentityDocumentStore
from core.secrets.bootstrap import resolve_bootstrap_secret
from core.shared.installer import (
    DEFAULT_MONGODB_PASSWORD_REF,
    InstallerConfig,
    apply_initial_admin_password,
    default_install_env_path,
    default_live_systemd_dir,
    default_systemd_dir,
    render_install_plan,
    write_install_plan,
)
from scripts.install_maverick import (
    INTERNAL_APPLY_ADMIN_PASSWORD_FLAG,
    _apply_initial_admin_password,
    _mongodb_apt_repository_line,
    _mongodb_endpoint,
    _prepare_mongodb,
    _running_inside_install_venv,
    build_config,
    main as installer_main,
    parse_args,
)


class InstallerSecretRenderingTestCase(unittest.TestCase):
    def secret_args(self, output_root: Path) -> list[str]:
        return [
            "--secret-key-file",
            str(output_root / "bootstrap-secrets" / "secret-store.key"),
            "--bootstrap-secret-store-root",
            str(output_root / "bootstrap-secrets"),
        ]

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

    def test_initial_admin_password_is_written_to_identity_store_not_env(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory(prefix="maverick-install-") as temp_dir:
            install_root = Path(temp_dir)
            config = replace(
                self.make_config(repo_root, install_root=install_root),
                json_control_store_root="control-plane/json",
                admin_password="install-admin-password",
            )

            rendered = render_install_plan(config)
            write_install_plan(rendered)
            apply_initial_admin_password(config)
            env_file = (install_root / ".env.maverick").read_text(encoding="utf-8")
            collections = build_control_plane_collections(
                ControlStoreSettings(kind="json", json_root=install_root / "control-plane" / "json")
            )

            self.assertNotIn("install-admin-password", env_file)
            self.assertNotIn("MAVERICK_ADMIN_PASSWORD", env_file)
            self.assertEqual(
                authenticate_password(
                    IdentityDocumentStore(collections.identity),
                    username="admin",
                    password="install-admin-password",
                ).username,
                "admin",
            )

    def test_noninteractive_live_install_requires_admin_password_file(self) -> None:
        args = parse_args(["--local-only", "--skip-bootstrap", "--skip-verify", "--yes"])

        with self.assertRaises(SystemExit):
            build_config(args, interactive=False)

    def test_admin_password_file_configures_initial_password(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-install-") as temp_dir:
            password_file = Path(temp_dir) / "admin-password.txt"
            password_file.write_text("install-admin-password\n", encoding="utf-8")
            args = parse_args(
                [
                    "--local-only",
                    "--skip-bootstrap",
                    "--skip-verify",
                    "--yes",
                    "--admin-password-file",
                    str(password_file),
                ]
            )

            config = build_config(args, interactive=False)

        self.assertEqual(config.admin_password, "install-admin-password")

    def test_installer_main_installs_mongo_extra_when_mongo_control_store_is_selected(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory(prefix="maverick-install-") as temp_dir:
            output_root = Path(temp_dir) / "install"
            with patch("core.shared.installer.subprocess.run") as mocked_run:
                exit_code = installer_main(
                    [
                        "--local-only",
                        "--control-store",
                        "mongo",
                        "--output-root",
                        str(output_root),
                        "--install-env",
                        str(output_root / "maverick.env"),
                        "--render-only",
                        "--yes",
                        *self.secret_args(output_root),
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(mocked_run.call_args_list[0].args[0], [str(repo_root / "scripts" / "bootstrap_local.sh")])
        self.assertEqual(mocked_run.call_args_list[0].kwargs["env"]["MAVERICK_PYPROJECT_EXTRAS"], "dev,mongo")

    def test_initial_admin_password_for_mongo_runs_inside_install_venv(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-install-") as temp_dir:
            repo_root = Path(temp_dir) / "repo"
            install_root = repo_root
            venv_python = repo_root / ".venv" / "bin" / "python"
            venv_python.parent.mkdir(parents=True, exist_ok=True)
            venv_python.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            config = replace(
                self.make_config(repo_root, install_root=install_root),
                control_store="mongo",
                admin_password="install-admin-password",
            )

            with patch("scripts.install_maverick.subprocess.run") as mocked_run:
                _apply_initial_admin_password(config)

        command = mocked_run.call_args.args[0]
        payload = json.loads(mocked_run.call_args.kwargs["input"])
        self.assertEqual(command[0], str(venv_python))
        self.assertEqual(command[-1], INTERNAL_APPLY_ADMIN_PASSWORD_FLAG)
        self.assertEqual(payload["control_store"], "mongo")
        self.assertEqual(payload["admin_password"], "install-admin-password")
        self.assertNotIn("install-admin-password", command)

    def test_initial_admin_password_installs_mongo_extra_when_current_venv_lacks_driver(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        config = replace(
            self.make_config(repo_root, install_root=repo_root),
            control_store="mongo",
            admin_password="install-admin-password",
        )

        with patch("scripts.install_maverick._running_inside_install_venv", return_value=True), patch(
            "scripts.install_maverick.importlib.util.find_spec",
            return_value=None,
        ), patch("scripts.install_maverick.subprocess.run") as mocked_run, patch(
            "scripts.install_maverick.apply_initial_admin_password"
        ):
            _apply_initial_admin_password(config)

        self.assertEqual(
            mocked_run.call_args.args[0],
            [sys.executable, "-m", "pip", "install", "-e", ".[mongo]"],
        )
        self.assertEqual(mocked_run.call_args.kwargs["cwd"], repo_root)

    def test_install_venv_detection_uses_python_prefix_not_resolved_executable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-install-") as temp_dir:
            repo_root = Path(temp_dir) / "repo"
            config = self.make_config(repo_root, install_root=repo_root)
            with patch("scripts.install_maverick.sys.prefix", str(repo_root / ".venv")):
                self.assertTrue(_running_inside_install_venv(config))
            with patch("scripts.install_maverick.sys.prefix", "/usr"):
                self.assertFalse(_running_inside_install_venv(config))

    def test_prepare_mongodb_installs_local_service_when_unreachable(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        config = replace(self.make_config(repo_root, install_root=repo_root), control_store="mongo")

        with patch("scripts.install_maverick._mongodb_reachable", return_value=False), patch(
            "scripts.install_maverick._install_or_start_local_mongodb"
        ) as mocked_install, patch("scripts.install_maverick._mongodb_becomes_reachable", return_value=True):
            _prepare_mongodb(config, assume_yes=True)

        mocked_install.assert_called_once_with()

    def test_prepare_mongodb_rejects_unreachable_remote_uri(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        config = replace(
            self.make_config(repo_root, install_root=repo_root),
            control_store="mongo",
            mongodb_uri="mongodb://db.example.test:27017/maverick",
        )

        with patch("scripts.install_maverick._mongodb_reachable", return_value=False), self.assertRaises(SystemExit):
            _prepare_mongodb(config, assume_yes=True)

    def test_mongodb_endpoint_parses_auth_and_port(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        config = replace(
            self.make_config(repo_root, install_root=repo_root),
            mongodb_uri="mongodb://user:secret@127.0.0.1:27018/maverick",
        )

        endpoint = _mongodb_endpoint(config)

        self.assertEqual(endpoint.host, "127.0.0.1")
        self.assertEqual(endpoint.port, 27018)

    def test_mongodb_repo_line_uses_supported_ubuntu_codename(self) -> None:
        with patch("scripts.install_maverick._read_os_release", return_value={"ID": "ubuntu", "VERSION_CODENAME": "noble"}):
            self.assertIn("noble/mongodb-org/8.0", _mongodb_apt_repository_line())


if __name__ == "__main__":
    unittest.main()
