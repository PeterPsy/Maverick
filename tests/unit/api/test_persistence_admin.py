"""Tests for control-plane persistence adapter administration."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.api.persistence_admin import apply_persistence_migration, dry_run_persistence_migration, target_settings_from_payload
from core.api.persistence_cleanup_worker import run_pending_cleanup_plans
from core.api.control_store import ControlStoreSettings
from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.providers.models import ProviderCredentialBinding
from core.runtime.runtime_session import RuntimeApiTokenRecord


class PersistenceAdminTestCase(unittest.TestCase):
    def test_mongo_target_payload_preserves_auth_secret_ref_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._make_repo_root(Path(temp_dir) / "maverick")

            settings = target_settings_from_payload(
                repository_root=repo_root,
                payload={
                    "kind": "mongo",
                    "mongodb_uri": "mongodb://127.0.0.1:27017/maverick",
                    "mongodb_database": "maverick",
                    "mongodb_username": "maverick",
                    "mongodb_password_ref": "platform:secret-alias/mongodb-password",
                },
            )

            self.assertEqual(settings.mongo_username, "maverick")
            self.assertEqual(settings.mongo_password_ref, "platform:secret-alias/mongodb-password")

    def test_json_to_json_migration_copies_all_control_plane_collections_and_updates_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._make_repo_root(Path(temp_dir) / "maverick")
            env_file = repo_root / ".env.maverick"
            env_file.write_text(
                "\n".join(
                    [
                        "MAVERICK_ADMIN_USERNAME=admin",
                        "MAVERICK_ADMIN_PASSWORD=maverick",
                        "MAVERICK_RUNTIME_API_SECRET=test-runtime-secret",
                        "MAVERICK_SECRET_STORE_KEY=test-secret-key",
                        "MAVERICK_CONTROL_STORE=json",
                        "MAVERICK_JSON_CONTROL_STORE_ROOT=source-control",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {
                    "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                    "MAVERICK_ADMIN_USERNAME": "admin",
                    "MAVERICK_ADMIN_PASSWORD": "maverick",
                    "MAVERICK_RUNTIME_API_SECRET": "test-runtime-secret",
                    "MAVERICK_SECRET_STORE_KEY": "test-secret-key",
                    "MAVERICK_CONTROL_STORE": "json",
                    "MAVERICK_JSON_CONTROL_STORE_ROOT": "source-control",
                    "MAVERICK_SERVICE_ENV_FILE": str(env_file),
                },
                clear=True,
            ):
                state = bootstrap_platform_state(start_path=repo_root)
                now = datetime(2026, 4, 30, 12, 0, tzinfo=UTC)
                state.provider_store.save_provider_binding(
                    ProviderCredentialBinding(
                        binding_id="binding:codex:default",
                        provider_id="codex",
                        workspace_id="default",
                        secret_ref="alias:OPENAI_API_KEY",
                        label="Default Codex",
                        status="active",
                        created_at=now,
                        updated_at=now,
                    )
                )
                state.runtime_store.save_api_token(
                    RuntimeApiTokenRecord(
                        token_id="token-1",
                        session_id="session-1",
                        workspace_id="default",
                        mode="full-access",
                        status="active",
                        issued_at=now,
                        expires_at=now + timedelta(hours=1),
                    )
                )

                dry_run = dry_run_persistence_migration(
                    repository_root=repo_root,
                    source_settings=state.control_store_settings,
                    source_collections=state.control_plane_collections,
                    target_payload={"kind": "json", "json_root": "target-control"},
                )
                applied = apply_persistence_migration(
                    repository_root=repo_root,
                    source_settings=state.control_store_settings,
                    source_collections=state.control_plane_collections,
                    target_payload={"kind": "json", "json_root": "target-control"},
                )

            self.assertEqual(dry_run["status"], "dry_run")
            self.assertEqual(applied["status"], "prepared")
            self.assertFalse(applied["active_adapter_changed"])
            self.assertTrue(applied["restart_required_for_cutover"])
            self.assertTrue(applied["env_file"]["updated"])
            self.assertEqual(state.control_store_settings.json_root, repo_root / "source-control")
            provider_bindings = json.loads((repo_root / "target-control" / "providers" / "bindings.json").read_text())
            api_tokens = json.loads((repo_root / "target-control" / "runtime" / "api_tokens.json").read_text())
            env_content = env_file.read_text(encoding="utf-8")
            self.assertEqual(provider_bindings[0]["binding_id"], "binding:codex:default")
            self.assertEqual(api_tokens[0]["token_id"], "token-1")
            self.assertIn("MAVERICK_CONTROL_STORE=json", env_content)
            self.assertIn("MAVERICK_JSON_CONTROL_STORE_ROOT=target-control", env_content)

    def test_admin_http_surface_requires_admin_and_exposes_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._make_repo_root(Path(temp_dir) / "maverick")
            with patch.dict(
                os.environ,
                {
                    "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                    "MAVERICK_ADMIN_USERNAME": "admin",
                    "MAVERICK_ADMIN_PASSWORD": "maverick",
                    "MAVERICK_RUNTIME_API_SECRET": "test-runtime-secret",
                    "MAVERICK_SECRET_STORE_KEY": "test-secret-key",
                    "MAVERICK_CONTROL_STORE": "json",
                },
                clear=True,
            ):
                state = bootstrap_platform_state(start_path=repo_root)
                app = PlatformHost(state, start_path=state.repository_root)
                unauthenticated_status, unauthenticated, _headers = self._invoke(app, path="/api/admin/persistence")
                cookie = self._login(app)
                status, payload, _headers = self._invoke(app, path="/api/admin/persistence", cookie=cookie)

            self.assertEqual(unauthenticated_status, 401)
            self.assertEqual(unauthenticated["error"], "authentication_required")
            self.assertEqual(status, 200)
            self.assertEqual(payload["active_adapter"]["kind"], "json")
            self.assertIn("provider_credential_bindings", {item["name"] for item in payload["collections"]})

    def test_source_deletion_requires_backend_restart_cutover(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._make_repo_root(Path(temp_dir) / "maverick")
            with patch.dict(
                os.environ,
                {
                    "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                    "MAVERICK_ADMIN_USERNAME": "admin",
                    "MAVERICK_ADMIN_PASSWORD": "maverick",
                    "MAVERICK_RUNTIME_API_SECRET": "test-runtime-secret",
                    "MAVERICK_SECRET_STORE_KEY": "test-secret-key",
                    "MAVERICK_CONTROL_STORE": "json",
                    "MAVERICK_JSON_CONTROL_STORE_ROOT": "source-control",
                },
                clear=True,
            ):
                state = bootstrap_platform_state(start_path=repo_root)

                with self.assertRaisesRegex(ValueError, "requires `restart_backend=true`"):
                    apply_persistence_migration(
                        repository_root=repo_root,
                        source_settings=state.control_store_settings,
                        source_collections=state.control_plane_collections,
                        target_payload={
                            "kind": "json",
                            "json_root": "target-control",
                            "delete_source": True,
                        },
                    )

    def test_pending_cleanup_runs_on_startup_when_target_adapter_is_active(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._make_repo_root(Path(temp_dir) / "maverick")
            source_root = repo_root / "source-control"
            target_root = repo_root / "target-control"
            source_file = source_root / "workspaces" / "workspaces.json"
            target_file = target_root / "workspaces" / "workspaces.json"
            source_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.parent.mkdir(parents=True, exist_ok=True)
            source_file.write_text('[{"workspace_id":"old"}]\n', encoding="utf-8")
            target_file.write_text('[{"workspace_id":"new"}]\n', encoding="utf-8")
            plan_root = repo_root / ".maverick" / "persistence-cleanup"
            plan_root.mkdir(parents=True)
            plan_path = plan_root / "pending.json"
            plan_path.write_text(
                json.dumps(
                    {
                        "repository_root": str(repo_root),
                        "source_adapter": {
                            "kind": "json",
                            "json_root": str(source_root),
                            "mongo_uri": None,
                            "mongo_database": "maverick",
                        },
                        "target_adapter": {
                            "kind": "json",
                            "json_root": str(target_root),
                            "mongo_uri": None,
                            "mongo_database": "maverick",
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            results = run_pending_cleanup_plans(
                repository_root=repo_root,
                active_settings=ControlStoreSettings(kind="json", json_root=target_root),
            )

            self.assertEqual(results[0]["status"], "completed")
            self.assertFalse(source_root.exists())
            self.assertTrue(target_file.exists())
            self.assertTrue(plan_path.with_suffix(".done.json").exists())

    def test_json_source_cleanup_deletes_json_root_when_target_is_mongo(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._make_repo_root(Path(temp_dir) / "maverick")
            source_root = repo_root / "control-plane-json"
            source_file = source_root / "workspaces" / "workspaces.json"
            source_file.parent.mkdir(parents=True, exist_ok=True)
            source_file.write_text('[{"workspace_id":"old"}]\n', encoding="utf-8")
            plan_root = repo_root / ".maverick" / "persistence-cleanup"
            plan_root.mkdir(parents=True)
            plan_path = plan_root / "pending.json"
            plan_path.write_text(
                json.dumps(
                    {
                        "repository_root": str(repo_root),
                        "source_adapter": {
                            "kind": "json",
                            "json_root": str(source_root),
                            "mongo_uri": None,
                            "mongo_database": "maverick",
                        },
                        "target_adapter": {
                            "kind": "mongo",
                            "json_root": str(source_root),
                            "mongo_uri": "mongodb://127.0.0.1:27017/maverick",
                            "mongo_database": "maverick",
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            results = run_pending_cleanup_plans(
                repository_root=repo_root,
                active_settings=ControlStoreSettings(
                    kind="mongo",
                    json_root=source_root,
                    mongo_uri="mongodb://127.0.0.1:27017/maverick",
                    mongo_database="maverick",
                ),
            )

            self.assertEqual(results[0]["status"], "completed")
            self.assertFalse(source_root.exists())
            self.assertTrue(plan_path.with_suffix(".done.json").exists())

    def _make_repo_root(self, repo_root: Path) -> Path:
        for name in ("core", "apps", "workspaces", "docs", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        return repo_root

    def _login(self, app: PlatformHost) -> str:
        status, _payload, headers = self._invoke(
            app,
            path="/api/auth/login",
            method="POST",
            body={"username": "admin", "password": "maverick"},
        )
        self.assertEqual(status, 200)
        return headers["Set-Cookie"].split(";", 1)[0]

    def _invoke(
        self,
        app: PlatformHost,
        *,
        path: str,
        method: str = "GET",
        body: dict | None = None,
        cookie: str | None = None,
    ) -> tuple[int, dict, dict[str, str]]:
        payload = json.dumps(body or {}).encode("utf-8") if body is not None else b""
        headers: dict[str, str] = {}
        environ = {
            "PATH_INFO": path,
            "REQUEST_METHOD": method,
            "CONTENT_LENGTH": str(len(payload)),
            "CONTENT_TYPE": "application/json",
            "QUERY_STRING": "",
            "wsgi.input": BytesIO(payload),
        }
        if cookie is not None:
            environ["HTTP_COOKIE"] = cookie

        def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
            headers.update(dict(response_headers))
            headers["__status__"] = status

        body_bytes = b"".join(app(environ, start_response))
        return int(headers["__status__"].split()[0]), json.loads(body_bytes.decode("utf-8")), headers


if __name__ == "__main__":
    unittest.main()
