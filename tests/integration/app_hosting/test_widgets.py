"""Tests for registry-driven app widget discovery and mounting."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import json
import os
import shutil
import tempfile
import unittest

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.api.app_frame_scope import (
    APP_FRAME_APP_ID_SCOPE_KEY,
    APP_FRAME_MOUNT_APP_ID_SCOPE_KEY,
    APP_FRAME_PROXY_SCOPE_KEY,
)
from core.apps.contracts import (
    build_app_contract,
    build_app_distribution,
    build_app_entrypoints,
    build_app_lifecycle,
    build_parsed_app_contract,
    build_widget_actions,
    build_widget_declaration,
    build_widget_frontend,
    write_app_contract_file,
)
from core.apps.service import (
    install_store_app,
    install_workspace_local_app,
    register_app_source_from_contract,
    register_workspace_local_app_project_from_contract,
    transition_workspace_app_status,
)
from tests.support.markers import slow_test_class


CHECKLIST_APP_FRAME_SCOPE = {
    APP_FRAME_PROXY_SCOPE_KEY: True,
    APP_FRAME_APP_ID_SCOPE_KEY: "checklists",
    APP_FRAME_MOUNT_APP_ID_SCOPE_KEY: "checklists",
}


@slow_test_class("slow widget integration suite; run with scripts/test_suite.py --level slow")
class WidgetsTestCase(unittest.TestCase):
    """Verify widget contracts, registry lookup, context, and frontend mount."""

    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick"
        for name in ("core", "apps", "workspaces", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        return repo_root

    def write_widget_app(self, repo_root: Path, *, spa_fallback: bool = True) -> str:
        app_root = repo_root / "apps" / "checklists"
        widget_root = app_root / "frontend" / "dist" / "widgets" / "design-checklist"
        backend_root = app_root / "backend"
        widget_root.mkdir(parents=True, exist_ok=True)
        backend_root.mkdir(parents=True, exist_ok=True)
        (widget_root / "index.html").write_text(
            "<link rel='stylesheet' href='/api/apps/widgets/checklists/design-checklist/frontend/styles.css'>"
            "<div id='widget'>Checklist widget</div>"
            "<script src='/api/apps/widgets/checklists/design-checklist/frontend/main.js'></script>",
            encoding="utf-8",
        )
        (widget_root / "styles.css").write_text("#widget { color: red; }\n", encoding="utf-8")
        (widget_root / "main.js").write_text("document.body.dataset.widgetLoaded = 'true';\n", encoding="utf-8")
        (backend_root / "app_backend.py").write_text("print('backend')\n", encoding="utf-8")
        parsed = build_parsed_app_contract(
            app_id="checklists",
            name="Checklists",
            version="1.0.0",
            description="Checklist widget owner.",
            publisher="maverick",
            contract=build_app_contract(
                entrypoints=build_app_entrypoints(backend="backend/app_backend.py"),
                widgets=[
                    build_widget_declaration(
                        widget_id="design-checklist",
                        host="widget-host",
                        content_kinds=["checklist.design"],
                        frontend=build_widget_frontend(
                            mount="frontend/dist/widgets/design-checklist",
                            spa_fallback=spa_fallback,
                        ),
                        actions=build_widget_actions(backend=True),
                    )
                ],
            ),
        )
        write_app_contract_file(app_root, parsed)
        return str(app_root)

    def invoke(
        self,
        app,
        *,
        path: str,
        method: str = "GET",
        body: dict | None = None,
        cookie: str | None = None,
        query_string: str = "",
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[int, bytes, dict[str, str]]:
        payload = b""
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
        headers: dict[str, str] = {}
        environ = {
            "PATH_INFO": path,
            "REQUEST_METHOD": method,
            "CONTENT_LENGTH": str(len(payload)),
            "CONTENT_TYPE": "application/json",
            "QUERY_STRING": query_string,
            "wsgi.input": BytesIO(payload),
        }
        if cookie is not None:
            environ["HTTP_COOKIE"] = cookie
        for key, value in (extra_headers or {}).items():
            environ[key] = value

        def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
            headers.update(dict(response_headers))
            headers["__status__"] = status

        result = b"".join(app(environ, start_response))
        return int(headers["__status__"].split()[0]), result, headers

    def login(self, app) -> str:
        status, _body, headers = self.invoke(
            app,
            path="/api/auth/login",
            method="POST",
            body={
                "username": os.environ.get("MAVERICK_ADMIN_USERNAME", "admin"),
                "password": os.environ.get("MAVERICK_ADMIN_PASSWORD", "maverick"),
            },
        )
        self.assertEqual(status, 200)
        return headers["Set-Cookie"].split(";", 1)[0]

    def install_widget_app(self):
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        source = register_app_source_from_contract(
            state.app_store,
            source_kind="platform",
            source_path=self.write_widget_app(repo_root),
        )
        install_store_app(
            state.app_store,
            source_id=source.source_id,
            workspace_id="default",
            start_path=repo_root,
            observability_store=state.observability_store,
        )
        return repo_root, state

    def test_widget_registry_requires_auth_and_filters_by_host_and_kind(self) -> None:
        repo_root, state = self.install_widget_app()
        app = PlatformHost(state, start_path=repo_root)

        status_guest, guest_body, _guest_headers = self.invoke(
            app,
            path="/api/apps/widgets",
            query_string="host=widget-host&content_kind=checklist.design",
        )
        cookie = self.login(app)
        status_user, user_body, _user_headers = self.invoke(
            app,
            path="/api/apps/widgets",
            query_string="host=widget-host&content_kind=checklist.design",
            cookie=cookie,
        )
        payload = json.loads(user_body.decode("utf-8"))

        self.assertEqual(status_guest, 401)
        self.assertIn(b"authentication_required", guest_body)
        self.assertEqual(status_user, 200)
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(payload["items"][0]["owner_app_id"], "checklists")
        self.assertEqual(payload["items"][0]["widget_id"], "design-checklist")
        self.assertNotIn("requester_token", payload["items"][0])
        self.assertNotIn("source_root", payload["items"][0])
        self.assertNotIn("source_path", payload["items"][0])

    def test_widget_frontend_assets_require_the_isolated_authenticated_proxy(self) -> None:
        repo_root, state = self.install_widget_app()
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        status_html, html_body, _html_headers = self.invoke(app, path="/api/apps/widgets/checklists/design-checklist/frontend/")
        status_css, css_body, css_headers = self.invoke(
            app,
            path="/api/apps/widgets/checklists/design-checklist/frontend/styles.css",
            cookie=cookie,
            extra_headers=CHECKLIST_APP_FRAME_SCOPE,
        )
        status_css_head, _css_head_body, css_head_headers = self.invoke(
            app,
            path="/api/apps/widgets/checklists/design-checklist/frontend/styles.css",
            method="HEAD",
            cookie=cookie,
            extra_headers=CHECKLIST_APP_FRAME_SCOPE,
        )
        status_js, js_body, js_headers = self.invoke(
            app,
            path="/api/apps/widgets/checklists/design-checklist/frontend/main.js",
            cookie=cookie,
            extra_headers=CHECKLIST_APP_FRAME_SCOPE,
        )

        self.assertEqual(status_html, 401)
        self.assertIn(b"authentication_required", html_body)
        self.assertEqual(status_css, 200)
        self.assertNotIn("Access-Control-Allow-Origin", css_headers)
        self.assertIn(b"color: red", css_body)
        self.assertEqual(status_css_head, 200)
        self.assertNotIn("Access-Control-Allow-Origin", css_head_headers)
        self.assertEqual(status_js, 200)
        self.assertNotIn("Access-Control-Allow-Origin", js_headers)
        self.assertIn(b"widgetLoaded", js_body)

    def test_disabled_app_widgets_are_not_listed(self) -> None:
        repo_root, state = self.install_widget_app()
        transition_workspace_app_status(
            state.app_store,
            workspace_id="default",
            app_id="checklists",
            target_status="disabled",
        )
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        status, body, _headers = self.invoke(
            app,
            path="/api/apps/widgets",
            query_string="host=widget-host&content_kind=checklist.design",
            cookie=cookie,
        )

        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body.decode("utf-8"))["items"], [])

    def test_widget_registry_skips_workspace_local_app_with_missing_source(self) -> None:
        repo_root, state = self.install_widget_app()
        local_root = repo_root / "workspaces" / "default" / "apps" / "missing-widget"
        widget_root = local_root / "frontend" / "dist" / "widgets" / "preview"
        widget_root.mkdir(parents=True)
        (widget_root / "index.html").write_text("<div>Missing widget</div>", encoding="utf-8")
        parsed = build_parsed_app_contract(
            app_id="missing-widget",
            name="Missing Widget",
            version="1.0.0",
            description="Workspace-local widget app whose source was removed.",
            publisher="workspace",
            contract=build_app_contract(
                distribution=build_app_distribution(mode="workspace_local", source_access="editable"),
                lifecycle=build_app_lifecycle(health_check=False),
                entrypoints=build_app_entrypoints(frontend="frontend/dist"),
                widgets=[
                    build_widget_declaration(
                        widget_id="preview",
                        host="widget-host",
                        content_kinds=["checklist.design"],
                        frontend=build_widget_frontend(mount="frontend/dist/widgets/preview"),
                    )
                ],
            ),
        )
        write_app_contract_file(local_root, parsed)
        register_workspace_local_app_project_from_contract(
            state.app_store,
            workspace_id="default",
            project_root=str(local_root),
        )
        install_workspace_local_app(state.app_store, workspace_id="default", app_id="missing-widget", start_path=repo_root)
        shutil.rmtree(local_root)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        status, body, _headers = self.invoke(
            app,
            path="/api/apps/widgets",
            query_string="host=widget-host&content_kind=checklist.design",
            cookie=cookie,
        )
        payload = json.loads(body.decode("utf-8"))

        self.assertEqual(status, 200)
        self.assertEqual([item["owner_app_id"] for item in payload["items"]], ["checklists"])

    def test_widget_frontend_mount_serves_owner_frontend(self) -> None:
        repo_root, state = self.install_widget_app()
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        direct_status, direct_body, _direct_headers = self.invoke(
            app,
            path="/api/apps/widgets/checklists/design-checklist/frontend/",
            cookie=cookie,
        )
        status, body, _headers = self.invoke(
            app,
            path="/api/apps/widgets/checklists/design-checklist/frontend/",
            cookie=cookie,
            extra_headers=CHECKLIST_APP_FRAME_SCOPE,
        )

        self.assertEqual(direct_status, 403)
        self.assertIn(b"app_frame_isolation_required", direct_body)
        self.assertEqual(status, 200)
        self.assertIn(b"Checklist widget", body)

    def test_widget_frontend_mount_respects_spa_fallback_flag(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        source = register_app_source_from_contract(
            state.app_store,
            source_kind="platform",
            source_path=self.write_widget_app(repo_root, spa_fallback=False),
        )
        install_store_app(
            state.app_store,
            source_id=source.source_id,
            workspace_id="default",
            start_path=repo_root,
            observability_store=state.observability_store,
        )
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        status, body, _headers = self.invoke(
            app,
            path="/api/apps/widgets/checklists/design-checklist/frontend/missing-route",
            cookie=cookie,
            extra_headers=CHECKLIST_APP_FRAME_SCOPE,
        )

        self.assertEqual(status, 404)
        self.assertIn(b"Not found", body)

    def test_widget_context_token_contains_only_explicit_context(self) -> None:
        repo_root, state = self.install_widget_app()
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)
        status_create, create_body, _headers = self.invoke(
            app,
            path="/api/apps/widgets/context",
            method="POST",
            cookie=cookie,
            body={
                "host_app_id": "widget-host",
                "owner_app_id": "checklists",
                "widget_id": "design-checklist",
                "message_id": "msg-1",
                "content": {"kind": "checklist.design", "payload": {"id": "check_demo1234"}},
            },
        )
        create_payload = json.loads(create_body.decode("utf-8"))
        token = create_payload["context_token"]
        status_get, get_body, _get_headers = self.invoke(
            app,
            path=f"/api/apps/widgets/context/{token}",
            cookie=cookie,
        )
        context = json.loads(get_body.decode("utf-8"))["context"]

        self.assertEqual(status_create, 200)
        self.assertEqual(status_get, 200)
        self.assertEqual(context["workspace_id"], "default")
        self.assertEqual(context["user_id"], "user:admin")
        self.assertEqual(context["host_app_id"], "widget-host")
        self.assertEqual(context["owner_app_id"], "checklists")
        self.assertEqual(context["widget_id"], "design-checklist")
        self.assertNotIn("requester_app_id", context)
        self.assertNotIn("source_root", context)
        self.assertNotIn("source_path", context)

    def test_widget_context_rejects_incompatible_host_or_content_kind(self) -> None:
        repo_root, state = self.install_widget_app()
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        status, body, _headers = self.invoke(
            app,
            path="/api/apps/widgets/context",
            method="POST",
            cookie=cookie,
            body={
                "host_app_id": "widget-host",
                "owner_app_id": "checklists",
                "widget_id": "design-checklist",
                "message_id": "msg-1",
                "content": {"kind": "note.plain", "payload": {"title": "Plan"}},
            },
        )

        self.assertEqual(status, 403)
        self.assertIn(b"widget_not_compatible", body)

    def test_widget_context_does_not_claim_requester_identity(self) -> None:
        repo_root, state = self.install_widget_app()
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        lookup_status, lookup_body, _lookup_headers = self.invoke(
            app,
            path="/api/apps/widgets",
            query_string="host=widget-host&content_kind=checklist.design",
            cookie=cookie,
            extra_headers={"HTTP_REFERER": "http://localhost/apps/any-app/"},
        )
        status, body, _headers = self.invoke(
            app,
            path="/api/apps/widgets/context",
            method="POST",
            cookie=cookie,
            extra_headers={"HTTP_REFERER": "http://localhost/apps/any-app/"},
            body={
                "host_app_id": "widget-host",
                "owner_app_id": "checklists",
                "widget_id": "design-checklist",
                "message_id": "msg-1",
                "content": {"kind": "checklist.design", "payload": {"id": "check_demo1234"}},
            },
        )
        lookup_payload = json.loads(lookup_body.decode("utf-8"))
        context = json.loads(body.decode("utf-8"))["context"]

        self.assertEqual(lookup_status, 200)
        self.assertNotIn("requester_token", lookup_payload["items"][0])
        self.assertEqual(status, 200)
        self.assertEqual(context["host_app_id"], "widget-host")
        self.assertNotIn("requester_app_id", context)

    def test_widget_operations_emit_observability_events(self) -> None:
        repo_root, state = self.install_widget_app()
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        self.invoke(
            app,
            path="/api/apps/widgets",
            query_string="host=widget-host&content_kind=checklist.design",
            cookie=cookie,
        )
        self.invoke(
            app,
            path="/api/apps/widgets/checklists/design-checklist/frontend/",
            cookie=cookie,
            extra_headers=CHECKLIST_APP_FRAME_SCOPE,
        )

        event_types = [event.event_type for event in state.observability_store.list_events(workspace_id="default")]
        self.assertIn("apps.widgets.lookup", event_types)
        self.assertIn("apps.widgets.mounted", event_types)


if __name__ == "__main__":
    unittest.main()
