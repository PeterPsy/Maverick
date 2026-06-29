from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import tempfile
import unittest
from unittest.mock import patch

from core.api.app_reference_payloads import normalize_reference_item
from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.app_sdk.cli import run_cli_json
from core.apps.models import AppVisibilityDeclaration
from core.apps.service import install_store_app, register_app_source_from_contract
from core.identity.service import create_user
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.service import create_runtime_session
from core.workspaces.service import ensure_workspace_membership
from tests.unit.api.app_reference_test_support import AppReferenceApiTestSupport


class AppReferencesApiTestCase(AppReferenceApiTestSupport, unittest.TestCase):
    def test_search_and_resolve_use_declared_app_reference_surface(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            self._write_reference_app(repo_root / "apps" / "records")
            with patch.dict(
                "os.environ",
                {
                    "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                    "MAVERICK_ADMIN_USERNAME": "admin",
                    "MAVERICK_ADMIN_PASSWORD": "maverick",
                },
            ):
                state = bootstrap_platform_state(start_path=repo_root)
            source = register_app_source_from_contract(
                state.app_store,
                source_kind="platform",
                source_path=str(repo_root / "apps" / "records"),
            )
            install_store_app(state.app_store, source_id=source.source_id, workspace_id="default", start_path=repo_root)
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            manifest_status, manifest_payload, _headers = self._invoke(
                app,
                path="/api/app-references/manifest",
                cookie=cookie,
            )
            search_status, search_payload, _headers = self._invoke(
                app,
                path="/api/app-references/search",
                method="POST",
                body={"query": "launch"},
                cookie=cookie,
            )
            resolve_status, resolve_payload, _headers = self._invoke(
                app,
                path="/api/app-references/resolve",
                method="POST",
                body={"app_id": "records", "entity_type": "record", "entity_id": "record-1"},
                cookie=cookie,
            )

        self.assertEqual(manifest_status, 200)
        self.assertEqual(manifest_payload["items"][0]["app_id"], "records")
        self.assertEqual(manifest_payload["items"][0]["entity_types"][0]["display_name"], "MCP Record")
        self.assertEqual(search_status, 200)
        self.assertEqual(search_payload["items"][0]["type"], "entity")
        self.assertEqual(search_payload["items"][0]["app_id"], "records")
        self.assertEqual(search_payload["items"][0]["entity_id"], "record-1")
        self.assertEqual(search_payload["items"][0]["deep_link"], "/app/records/records/record-1")
        self.assertEqual(resolve_status, 200)
        self.assertTrue(resolve_payload["exists"])
        self.assertEqual(resolve_payload["label"], "Launch record")

    def test_reference_routes_require_authentication(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            with patch.dict(
                "os.environ",
                {
                    "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                    "MAVERICK_ADMIN_USERNAME": "admin",
                    "MAVERICK_ADMIN_PASSWORD": "maverick",
                },
            ):
                state = bootstrap_platform_state(start_path=repo_root)
            app = PlatformHost(state, start_path=repo_root)

            status, payload, _headers = self._invoke(app, path="/api/app-references/manifest")

        self.assertEqual(status, 401)
        self.assertEqual(payload["error"], "authentication_required")

    def test_reference_routes_hide_disabled_and_invisible_providers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            with patch.dict(
                "os.environ",
                {
                    "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                    "MAVERICK_ADMIN_USERNAME": "admin",
                    "MAVERICK_ADMIN_PASSWORD": "maverick",
                },
            ):
                state = bootstrap_platform_state(start_path=repo_root)
            self._write_reference_app(repo_root / "apps" / "records")
            self._write_reference_app(
                repo_root / "apps" / "admin-records",
                app_id="admin-records",
                visibility=AppVisibilityDeclaration(platform_roles=["admin"], workspace_roles=None, capabilities=None),
            )
            disabled_source = register_app_source_from_contract(
                state.app_store,
                source_kind="platform",
                source_path=str(repo_root / "apps" / "records"),
            )
            hidden_source = register_app_source_from_contract(
                state.app_store,
                source_kind="platform",
                source_path=str(repo_root / "apps" / "admin-records"),
            )
            install_store_app(
                state.app_store,
                source_id=disabled_source.source_id,
                workspace_id="default",
                local_app_id="disabled-records",
                enabled=False,
                start_path=repo_root,
            )
            install_store_app(state.app_store, source_id=hidden_source.source_id, workspace_id="default", start_path=repo_root)
            member = create_user(state.identity_store, username="member.a", password="member-pass", platform_role="member")
            ensure_workspace_membership(
                state.workspace_store,
                membership_id=f"default:{member.user_id}",
                workspace_id="default",
                user_id=member.user_id,
                role="member",
            )
            app = PlatformHost(state, start_path=repo_root)
            member_cookie = self._login(app, username="member.a", password="member-pass")

            manifest_status, manifest_payload, _headers = self._invoke(
                app,
                path="/api/app-references/manifest",
                cookie=member_cookie,
            )
            search_status, search_payload, _headers = self._invoke(
                app,
                path="/api/app-references/search",
                method="POST",
                body={"query": "launch"},
                cookie=member_cookie,
            )

        self.assertEqual(manifest_status, 200)
        self.assertEqual(manifest_payload["items"], [])
        self.assertEqual(search_status, 200)
        self.assertEqual(search_payload["items"], [])

    def test_reference_errors_are_logged_but_not_exposed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            self._write_broken_reference_app(repo_root / "apps" / "broken")
            with patch.dict(
                "os.environ",
                {
                    "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                    "MAVERICK_ADMIN_USERNAME": "admin",
                    "MAVERICK_ADMIN_PASSWORD": "maverick",
                },
            ):
                state = bootstrap_platform_state(start_path=repo_root)
            source = register_app_source_from_contract(
                state.app_store,
                source_kind="platform",
                source_path=str(repo_root / "apps" / "broken"),
            )
            install_store_app(state.app_store, source_id=source.source_id, workspace_id="default", start_path=repo_root)
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            search_status, search_payload, _headers = self._invoke(
                app,
                path="/api/app-references/search",
                method="POST",
                body={"query": "launch"},
                cookie=cookie,
            )
            resolve_status, resolve_payload, _headers = self._invoke(
                app,
                path="/api/app-references/resolve",
                method="POST",
                body={"app_id": "broken", "entity_type": "record", "entity_id": "record-1"},
                cookie=cookie,
            )

        self.assertEqual(search_status, 200)
        self.assertEqual(search_payload["errors"], [{"app_id": "broken", "error": "reference_search_failed"}])
        self.assertEqual(resolve_status, 500)
        self.assertEqual(resolve_payload, {"error": "reference_resolve_failed"})

    def test_reference_tools_use_local_app_identity_and_data_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            self._write_reference_app(repo_root / "apps" / "records")
            with patch.dict(
                "os.environ",
                {
                    "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                    "MAVERICK_ADMIN_USERNAME": "admin",
                    "MAVERICK_ADMIN_PASSWORD": "maverick",
                },
            ):
                state = bootstrap_platform_state(start_path=repo_root)
            source = register_app_source_from_contract(
                state.app_store,
                source_kind="platform",
                source_path=str(repo_root / "apps" / "records"),
            )
            install_store_app(
                state.app_store,
                source_id=source.source_id,
                workspace_id="default",
                local_app_id="records-a",
                start_path=repo_root,
            )
            install_store_app(
                state.app_store,
                source_id=source.source_id,
                workspace_id="default",
                local_app_id="records-b",
                start_path=repo_root,
            )
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            first_status, first_payload, _headers = self._invoke(
                app,
                path="/api/app-references/search",
                method="POST",
                body={"query": "launch", "app_ids": ["records-a"]},
                cookie=cookie,
            )
            second_status, second_payload, _headers = self._invoke(
                app,
                path="/api/app-references/search",
                method="POST",
                body={"query": "launch", "app_ids": ["records-b"]},
                cookie=cookie,
            )

        self.assertEqual(first_status, 200)
        self.assertEqual(first_payload["items"][0]["app_id"], "records-a")
        self.assertEqual(first_payload["items"][0]["label"], "Launch record records-a")
        self.assertEqual(first_payload["items"][0]["deep_link"], "/app/records-a/records/record-1")
        self.assertEqual(second_status, 200)
        self.assertEqual(second_payload["items"][0]["app_id"], "records-b")
        self.assertEqual(second_payload["items"][0]["label"], "Launch record records-b")
        self.assertEqual(second_payload["items"][0]["deep_link"], "/app/records-b/records/record-1")

    def test_registry_and_cli_use_local_mount_and_public_id_separately(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            self._write_frontend_app(repo_root / "apps" / "vendor-records")
            with patch.dict(
                "os.environ",
                {
                    "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                    "MAVERICK_ADMIN_USERNAME": "admin",
                    "MAVERICK_ADMIN_PASSWORD": "maverick",
                },
            ):
                state = bootstrap_platform_state(start_path=repo_root)
            source = register_app_source_from_contract(
                state.app_store,
                source_kind="platform",
                source_path=str(repo_root / "apps" / "vendor-records"),
            )
            binding = install_store_app(
                state.app_store,
                source_id=source.source_id,
                workspace_id="default",
                local_app_id="records-local",
                start_path=repo_root,
            )
            state.app_store.save_workspace_app_binding(replace(binding, mount_app_id="records-mount"))
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            registry_status, registry_payload, _headers = self._invoke(app, path="/api/apps", cookie=cookie)
            frontend_status, frontend_body, _headers = self._invoke_raw(
                app,
                path="/apps/records-mount/",
                cookie=cookie,
            )
            cli_payload = run_cli_json(["apps", "list", "--json"], state=state, repository_root=repo_root)

        registry_item = next(item for item in registry_payload["items"] if item["app_id"] == "records-local")
        cli_item = next(item for item in cli_payload["apps"] if item["app_id"] == "records-local")
        self.assertEqual(registry_status, 200)
        self.assertEqual(registry_item["public_app_id"], "vendor-records")
        self.assertEqual(registry_item["mount_app_id"], "records-mount")
        self.assertEqual(registry_item["frontend_mount"], "/apps/records-mount/")
        self.assertEqual(registry_item["frontend_role"], "workspace")
        self.assertTrue(registry_item["frontend_launchable"])
        self.assertEqual(frontend_status, 200)
        self.assertIn(b"Vendor Records", frontend_body)
        self.assertEqual(cli_item["public_app_id"], "vendor-records")
        self.assertEqual(cli_item["mount_app_id"], "records-mount")
        self.assertEqual(cli_item["capabilities"]["frontend"], {"mounted": True, "role": "workspace", "launchable": True})

    def test_reference_payload_entity_type_must_match_requested_declared_type(self) -> None:
        provider = {
            "app_id": "records",
            "public_app_id": "records",
            "entities": [{"entity_type": "record"}],
        }

        self.assertIsNone(
            normalize_reference_item(
                {"entity_type": "other", "entity_id": "record-1", "title": "Wrong type"},
                provider=provider,
                fallback_entity_type="record",
            )
        )
        self.assertIsNone(
            normalize_reference_item(
                {"entity_type": "record", "entity_id": "record-1", "title": "Undeclared type"},
                provider={**provider, "entities": [{"entity_type": "other"}]},
                fallback_entity_type="record",
            )
        )

    def test_runtime_turn_materializes_references_server_side(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            self._write_reference_app(repo_root / "apps" / "records")
            with patch.dict(
                "os.environ",
                {
                    "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                    "MAVERICK_ADMIN_USERNAME": "admin",
                    "MAVERICK_ADMIN_PASSWORD": "maverick",
                },
            ):
                state = bootstrap_platform_state(start_path=repo_root)
            source = register_app_source_from_contract(
                state.app_store,
                source_kind="platform",
                source_path=str(repo_root / "apps" / "records"),
            )
            install_store_app(state.app_store, source_id=source.source_id, workspace_id="default", start_path=repo_root)
            session = create_runtime_session(
                state.runtime_store,
                session_id="sess-1",
                workspace_id="default",
                agent_id="chat",
                start_path=repo_root,
            )
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)
            captured: dict[str, object] = {}

            def fake_submit_runtime_turn(*_args, **kwargs):
                captured["app_references"] = kwargs.get("app_references")
                materializer = kwargs.get("app_reference_materializer")
                if callable(materializer):
                    captured["materialized_app_references"] = materializer(kwargs.get("app_references") or [])
                now = datetime.now(timezone.utc)
                return RuntimeTurnRecord(
                    turn_id="turn-1",
                    session_id=session.session_id,
                    workspace_id=session.workspace_id,
                    status="queued",
                    input_text=kwargs["input_text"],
                    created_at=now,
                    updated_at=now,
                    started_at=None,
                    completed_at=None,
                    failure_reason=None,
                ), []

            with patch("core.api.runtime_api.submit_runtime_turn_async", side_effect=fake_submit_runtime_turn):
                status, _payload, _headers = self._invoke(
                    app,
                    path="/api/runtime/sessions/sess-1/turns",
                    method="POST",
                    body={
                        "input_text": "Review @Launch record [ref:records/record/record-1]",
                        "async": True,
                        "app_references": [
                            {
                                "type": "entity",
                                "app_id": "records",
                                "entity_type": "record",
                                "entity_id": "record-1",
                                "label": "Forged label",
                                "summary": "Forged summary",
                                "deep_link": "/app/records/private",
                            },
                            {
                                "type": "entity",
                                "app_id": "records",
                                "entity_type": "record",
                                "entity_id": "deleted",
                                "label": "Deleted but forged",
                                "summary": "Forged deleted summary",
                                "deep_link": "/app/records/private-deleted",
                            },
                        ],
                    },
                    cookie=cookie,
                )

        self.assertEqual(status, 202)
        self.assertEqual(
            captured["app_references"],
            [
                {
                    "type": "entity",
                    "app_id": "records",
                    "entity_type": "record",
                    "entity_id": "record-1",
                    "label": "record-1",
                    "summary": "",
                },
                {
                    "type": "entity",
                    "app_id": "records",
                    "entity_type": "record",
                    "entity_id": "deleted",
                    "label": "deleted",
                    "summary": "",
                },
            ],
        )
        self.assertEqual(
            captured["materialized_app_references"],
            [
                {
                    "type": "entity",
                    "app_id": "records",
                    "entity_type": "record",
                    "entity_id": "record-1",
                    "label": "Launch record",
                    "summary": "Safe summary",
                    "deep_link": "/app/records/records/record-1",
                },
                {
                    "type": "entity",
                    "app_id": "records",
                    "entity_type": "record",
                    "entity_id": "deleted",
                    "label": "deleted",
                    "summary": "",
                    "exists": False,
                },
            ],
        )

    def test_runtime_turn_rejects_empty_input_before_materializing_references(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            with patch.dict(
                "os.environ",
                {
                    "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                    "MAVERICK_ADMIN_USERNAME": "admin",
                    "MAVERICK_ADMIN_PASSWORD": "maverick",
                },
            ):
                state = bootstrap_platform_state(start_path=repo_root)
            create_runtime_session(
                state.runtime_store,
                session_id="sess-1",
                workspace_id="default",
                agent_id="chat",
                start_path=repo_root,
            )
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            with patch("core.api.runtime_api.materialize_runtime_app_references") as materialize:
                status, payload, _headers = self._invoke(
                    app,
                    path="/api/runtime/sessions/sess-1/turns",
                    method="POST",
                    body={
                        "input_text": "",
                        "app_references": [
                            {
                                "type": "entity",
                                "app_id": "records",
                                "entity_type": "record",
                                "entity_id": "record-1",
                            }
                        ],
                    },
                    cookie=cookie,
                )

        self.assertEqual(status, 400)
        self.assertEqual(payload, {"error": "empty_runtime_input"})
        materialize.assert_not_called()


if __name__ == "__main__":
    unittest.main()
