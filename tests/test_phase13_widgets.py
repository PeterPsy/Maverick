"""Tests for registry-driven app widget discovery and mounting."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import json
import shutil
import tempfile
import unittest

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.apps.contracts import (
    build_app_contract,
    build_app_entrypoints,
    build_parsed_app_contract,
    build_widget_actions,
    build_widget_declaration,
    build_widget_frontend,
    write_app_contract_file,
)
from core.apps.service import install_store_app, register_app_source_from_contract, transition_workspace_app_status


class Phase13WidgetsTestCase(unittest.TestCase):
    """Verify widget contracts, registry lookup, context, and frontend mount."""

    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick-v3"
        for name in ("core", "apps", "workspaces", "local-skills", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        (repo_root / "IMPLEMENTATION_TASKLIST.md").write_text("", encoding="utf-8")
        source_apps_root = Path(__file__).resolve().parents[1] / "apps"
        shutil.copytree(
            source_apps_root / "base-shell",
            repo_root / "apps" / "base-shell",
            ignore=shutil.ignore_patterns("node_modules"),
        )
        return repo_root

    def write_widget_app(self, repo_root: Path, *, spa_fallback: bool = True) -> str:
        app_root = repo_root / "apps" / "checklists"
        widget_root = app_root / "frontend" / "dist" / "widgets" / "design-checklist"
        backend_root = app_root / "backend"
        widget_root.mkdir(parents=True, exist_ok=True)
        backend_root.mkdir(parents=True, exist_ok=True)
        (widget_root / "index.html").write_text("<div id='widget'>Checklist widget</div>", encoding="utf-8")
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
                        host="chat",
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
            body={"username": "admin", "password": "maverick3"},
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
            query_string="host=chat&content_kind=checklist.design",
        )
        cookie = self.login(app)
        status_user, user_body, _user_headers = self.invoke(
            app,
            path="/api/apps/widgets",
            query_string="host=chat&content_kind=checklist.design",
            cookie=cookie,
        )
        payload = json.loads(user_body.decode("utf-8"))

        self.assertEqual(status_guest, 401)
        self.assertIn(b"authentication_required", guest_body)
        self.assertEqual(status_user, 200)
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(payload["items"][0]["owner_app_id"], "checklists")
        self.assertEqual(payload["items"][0]["widget_id"], "design-checklist")
        self.assertNotIn("source_root", payload["items"][0])
        self.assertNotIn("source_path", payload["items"][0])

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
            query_string="host=chat&content_kind=checklist.design",
            cookie=cookie,
        )

        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body.decode("utf-8"))["items"], [])

    def test_widget_frontend_mount_serves_owner_frontend(self) -> None:
        repo_root, state = self.install_widget_app()
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        status, body, _headers = self.invoke(
            app,
            path="/api/apps/widgets/checklists/design-checklist/frontend/",
            cookie=cookie,
        )

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
                "host_app_id": "chat",
                "owner_app_id": "checklists",
                "widget_id": "design-checklist",
                "message_id": "msg-1",
                "content": {"kind": "checklist.design", "payload": {"title": "Plan"}},
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
        self.assertEqual(context["host_app_id"], "chat")
        self.assertEqual(context["owner_app_id"], "checklists")
        self.assertEqual(context["widget_id"], "design-checklist")
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
                "host_app_id": "chat",
                "owner_app_id": "checklists",
                "widget_id": "design-checklist",
                "message_id": "msg-1",
                "content": {"kind": "note.plain", "payload": {"title": "Plan"}},
            },
        )

        self.assertEqual(status, 403)
        self.assertIn(b"widget_not_compatible", body)

    def test_widget_operations_emit_observability_events(self) -> None:
        repo_root, state = self.install_widget_app()
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        self.invoke(
            app,
            path="/api/apps/widgets",
            query_string="host=chat&content_kind=checklist.design",
            cookie=cookie,
        )
        self.invoke(app, path="/api/apps/widgets/checklists/design-checklist/frontend/", cookie=cookie)

        event_types = [event.event_type for event in state.observability_store.list_events(workspace_id="default")]
        self.assertIn("apps.widgets.lookup", event_types)
        self.assertIn("apps.widgets.mounted", event_types)


if __name__ == "__main__":
    unittest.main()
