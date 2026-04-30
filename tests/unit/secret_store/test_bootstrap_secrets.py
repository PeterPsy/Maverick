"""Tests for bootstrap-positioned core secrets."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.api.widget_context import sign_widget_context, verify_widget_context
from core.runtime.workspace_api_token import issue_workspace_api_token, verify_workspace_api_token
from core.secrets.bootstrap import create_bootstrap_secret_store, resolve_bootstrap_secret
from core.secrets.service import create_platform_secret


class BootstrapSecretsTestCase(unittest.TestCase):
    def test_bootstrap_secret_store_resolves_ref_without_raw_env_value(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            key_file = root / "secret-store.key"
            bootstrap_root = root / "bootstrap-secrets"
            key_file.write_text("bootstrap-key\n", encoding="utf-8")

            with patch.dict(
                os.environ,
                {
                    "MAVERICK_SECRET_KEY_FILE": str(key_file),
                    "MAVERICK_BOOTSTRAP_SECRET_STORE_ROOT": str(bootstrap_root),
                },
                clear=True,
            ):
                store = create_bootstrap_secret_store()
                create_platform_secret(
                    store,
                    label="Mongo Password",
                    raw_value="mongo-password-value",
                    alias="mongodb-password",
                )

                self.assertEqual(
                    resolve_bootstrap_secret("platform:secret-alias/mongodb-password"),
                    "mongo-password-value",
                )

            self.assertNotIn("mongo-password-value", (bootstrap_root / "values.json").read_text(encoding="utf-8"))

    def test_runtime_and_widget_signing_can_use_bootstrap_secret_refs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            key_file = root / "secret-store.key"
            bootstrap_root = root / "bootstrap-secrets"
            key_file.write_text("bootstrap-key\n", encoding="utf-8")

            with patch.dict(
                os.environ,
                {
                    "MAVERICK_SECRET_KEY_FILE": str(key_file),
                    "MAVERICK_BOOTSTRAP_SECRET_STORE_ROOT": str(bootstrap_root),
                    "MAVERICK_RUNTIME_API_SECRET_REF": "platform:secret-alias/runtime-api-secret",
                    "MAVERICK_WIDGET_CONTEXT_SECRET_REF": "platform:secret-alias/widget-context-secret",
                },
                clear=True,
            ):
                store = create_bootstrap_secret_store()
                create_platform_secret(
                    store,
                    label="Runtime API Secret",
                    raw_value="runtime-signing-secret",
                    alias="runtime-api-secret",
                )
                create_platform_secret(
                    store,
                    label="Widget Context Secret",
                    raw_value="widget-signing-secret",
                    alias="widget-context-secret",
                )

                token = issue_workspace_api_token(workspace_id="default", runtime_session_id="sess-1")
                self.assertEqual(verify_workspace_api_token(token)["workspace_id"], "default")

                context_token = sign_widget_context({"workspace_id": "default", "user": "admin"})
                self.assertEqual(verify_widget_context(context_token)["workspace_id"], "default")


if __name__ == "__main__":
    unittest.main()
