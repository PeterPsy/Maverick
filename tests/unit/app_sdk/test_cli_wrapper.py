"""Tests for the installed Maverick CLI wrapper."""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from core.api.platform_state import bootstrap_platform_state
from core.app_sdk.cli import main as cli_main
from core.identity.service import authenticate_password
from core.identity.errors import UserNotFoundError


class MaverickCliWrapperTestCase(unittest.TestCase):
    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick"
        for name in ("core", "apps", "workspaces", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        return repo_root

    def test_cli_wrapper_does_not_apply_bootstrap_admin_password_to_store(self) -> None:
        repo_root = self.make_repo_root()
        with patch.dict(
            os.environ,
            {
                "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                "MAVERICK_ADMIN_USERNAME": "admin",
                "MAVERICK_ADMIN_PASSWORD": "original-password",
                "MAVERICK_CONTROL_STORE": "json",
                "MAVERICK_JSON_CONTROL_STORE_ROOT": "data/control-plane/json",
            },
            clear=True,
        ):
            bootstrap_platform_state(start_path=repo_root)

        with patch.dict(
            os.environ,
            {
                "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                "MAVERICK_ADMIN_USERNAME": "admin",
                "MAVERICK_ADMIN_PASSWORD": "cli-process-password",
                "MAVERICK_CONTROL_STORE": "json",
                "MAVERICK_JSON_CONTROL_STORE_ROOT": "data/control-plane/json",
            },
            clear=True,
        ):
            with redirect_stdout(StringIO()):
                self.assertEqual(cli_main(["--repository-root", str(repo_root), "apps", "list", "--json"]), 0)

        state = bootstrap_platform_state(
            start_path=repo_root,
            apply_bootstrap_admin_password=False,
        )
        self.assertEqual(authenticate_password(state.identity_store, username="admin", password="original-password").user_id, "user:admin")
        with self.assertRaises(UserNotFoundError):
            authenticate_password(state.identity_store, username="admin", password="cli-process-password")


if __name__ == "__main__":
    unittest.main()
