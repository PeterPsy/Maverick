"""Shared helpers for Core Secrets HTTP API tests."""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
import json
import os
import unittest
from unittest.mock import patch

from core.apps.service import install_store_app, register_app_source_from_contract
from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from tests.support.repo import make_temp_repo_root, write_synthetic_platform_app


class SecretApiTestSupport(unittest.TestCase):
    """Test harness for invoking the Vault-facing Core Secrets API."""

    def invoke(
        self,
        app: PlatformHost,
        *,
        path: str,
        method: str = "GET",
        body: dict | None = None,
        cookie: str | None = None,
    ) -> tuple[int, dict, dict[str, str]]:
        payload = b"" if body is None else json.dumps(body).encode("utf-8")
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
        headers: dict[str, str] = {}

        def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
            headers.update(dict(response_headers))
            headers["__status__"] = status

        body_bytes = b"".join(app(environ, start_response))
        return int(headers["__status__"].split()[0]), json.loads(body_bytes.decode("utf-8")), headers

    def login(self, app: PlatformHost, *, username: str = "admin", password: str = "maverick") -> str:
        status, _payload, headers = self.invoke(
            app,
            path="/api/auth/login",
            method="POST",
            body={"username": username, "password": password},
        )
        self.assertEqual(status, 200)
        return headers["Set-Cookie"].split(";", 1)[0]

    def make_app(self) -> PlatformHost:
        repo_root = make_temp_repo_root(self)
        with patch.dict(
            os.environ,
            {
                "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                "MAVERICK_ADMIN_USERNAME": "admin",
                "MAVERICK_ADMIN_PASSWORD": "maverick",
            },
            clear=False,
        ):
            state = bootstrap_platform_state(start_path=repo_root, install_builtin_apps=False)
        return PlatformHost(state, start_path=state.repository_root)

    def enable_workspace_app(
        self,
        app: PlatformHost,
        *,
        app_id: str = "browser",
        workspace_id: str = "default",
        secret_read: list[str] | None = None,
        backend: bool = False,
        cli_commands: list[str] | None = None,
        mcp_tools: list[str] | None = None,
    ) -> None:
        app_root = write_synthetic_platform_app(
            app.state.repository_root,
            app_id=app_id,
            backend=backend,
            cli_commands=cli_commands,
            mcp_tools=mcp_tools,
        )
        if secret_read is not None:
            contract_path = app_root / "app_contract.json"
            payload = json.loads(contract_path.read_text(encoding="utf-8"))
            payload["permissions"]["secrets"]["read"] = secret_read
            contract_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        source = register_app_source_from_contract(
            app.state.app_store,
            source_kind="platform",
            source_path=str(app_root),
            source_id=f"platform:{app_id}",
            now=datetime.now(tz=UTC),
        )
        install_store_app(
            app.state.app_store,
            source_id=source.source_id,
            workspace_id=workspace_id,
            enabled=True,
            start_path=app.state.repository_root,
        )
