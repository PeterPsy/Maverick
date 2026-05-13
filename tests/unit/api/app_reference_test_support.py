from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path

from core.api.platform_host import PlatformHost
from core.apps.contracts import (
    build_app_capabilities,
    build_app_contract,
    build_app_entrypoints,
    build_parsed_app_contract,
    build_reference_entity_declaration,
    write_app_contract_file,
)
from core.apps.models import AppVisibilityDeclaration


class AppReferenceApiTestSupport:
    def _repo_root(self, temp_dir: str) -> Path:
        repo_root = Path(temp_dir) / "maverick"
        for name in ("core", "apps", "workspaces", "scripts", "docs"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        return repo_root

    def _write_reference_app(
        self,
        app_root: Path,
        *,
        app_id: str = "records",
        visibility: AppVisibilityDeclaration | None = None,
    ) -> None:
        tool_prefix = app_id.replace("-", "_")
        (app_root / "mcp").mkdir(parents=True, exist_ok=True)
        (app_root / "mcp" / "server.py").write_text(
            "from pathlib import Path\n"
            "import json, sys\n"
            "payload = json.loads(sys.stdin.read() or '{}')\n"
            "local_app_id = payload.get('app_id') or 'records'\n"
            "tool = payload.get('tool_name')\n"
            "args = payload.get('arguments') if isinstance(payload.get('arguments'), dict) else {}\n"
            "data_root_name = Path(payload.get('data_root') or local_app_id).name\n"
            "title = 'Launch record' if local_app_id == 'records' else f'Launch record {data_root_name}'\n"
            "item = {'app_id': local_app_id, 'entity_type': 'record', 'entity_id': 'record-1', 'title': title, 'summary': 'Safe summary', 'app_page': 'records/record-1', 'deep_link': f'/app/records/records/record-1'}\n"
            f"if tool == '{tool_prefix}_reference_search':\n"
            "    result = {'results': [item]}\n"
            f"elif tool == '{tool_prefix}_reference_resolve':\n"
            "    if args.get('entity_id') == 'record-1':\n"
            "        result = {'exists': True, **item}\n"
            "    else:\n"
            "        result = {'entity_type': 'record', 'entity_id': args.get('entity_id'), 'exists': False}\n"
            f"elif tool == '{tool_prefix}_reference_summarize':\n"
            "    if args.get('entity_id') == 'record-1':\n"
            "        result = {'summary': item['summary'], **item}\n"
            "    else:\n"
            "        result = {'entity_type': 'record', 'entity_id': args.get('entity_id'), 'exists': False, 'summary': ''}\n"
            "else:\n"
            "    result = {'entity_types': [{'entity_type': 'record', 'display_name': 'MCP Record'}]}\n"
            "print(json.dumps(result))\n",
            encoding="utf-8",
        )
        parsed = build_parsed_app_contract(
            app_id=app_id,
            name="Records",
            version="1.0.0",
            description="Record reference test app.",
            publisher="maverick",
            contract=build_app_contract(
                visibility=visibility,
                capabilities=build_app_capabilities(
                    mcp_tools=[
                        f"{tool_prefix}_reference_manifest",
                        f"{tool_prefix}_reference_search",
                        f"{tool_prefix}_reference_resolve",
                        f"{tool_prefix}_reference_summarize",
                    ],
                    reference_entities=[build_reference_entity_declaration(entity_type="record", display_name="Record")],
                ),
                entrypoints=build_app_entrypoints(mcp="mcp/server.py"),
            ),
        )
        write_app_contract_file(app_root, parsed)

    def _write_broken_reference_app(self, app_root: Path) -> None:
        (app_root / "mcp").mkdir(parents=True, exist_ok=True)
        (app_root / "mcp" / "server.py").write_text(
            "import json, sys\n"
            "payload = json.loads(sys.stdin.read() or '{}')\n"
            "tool = payload.get('tool_name')\n"
            "if tool == 'broken_reference_manifest':\n"
            "    print(json.dumps({'entity_types': [{'entity_type': 'record', 'display_name': 'Broken Record'}]}))\n"
            "else:\n"
            "    raise RuntimeError('internal path /tmp/private-entrypoint failed')\n",
            encoding="utf-8",
        )
        parsed = build_parsed_app_contract(
            app_id="broken",
            name="Broken",
            version="1.0.0",
            description="Broken reference test app.",
            publisher="maverick",
            contract=build_app_contract(
                capabilities=build_app_capabilities(
                    mcp_tools=[
                        "broken_reference_manifest",
                        "broken_reference_search",
                        "broken_reference_resolve",
                        "broken_reference_summarize",
                    ],
                    reference_entities=[build_reference_entity_declaration(entity_type="record", display_name="Record")],
                ),
                entrypoints=build_app_entrypoints(mcp="mcp/server.py"),
            ),
        )
        write_app_contract_file(app_root, parsed)

    def _write_frontend_app(self, app_root: Path, *, app_id: str = "vendor-records") -> None:
        (app_root / "frontend" / "dist").mkdir(parents=True, exist_ok=True)
        (app_root / "frontend" / "dist" / "index.html").write_text("<main>Vendor Records</main>", encoding="utf-8")
        parsed = build_parsed_app_contract(
            app_id=app_id,
            name="Vendor Records",
            version="1.0.0",
            description="Frontend mount test app.",
            publisher="maverick",
            contract=build_app_contract(entrypoints=build_app_entrypoints(frontend="frontend/dist")),
        )
        write_app_contract_file(app_root, parsed)

    def _login(self, app: PlatformHost, *, username: str = "admin", password: str = "maverick") -> str:
        status, _payload, headers = self._invoke(
            app,
            path="/api/auth/login",
            method="POST",
            body={"username": username, "password": password},
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
            "HTTP_HOST": "maverick.test",
            "wsgi.input": BytesIO(payload),
        }
        if method != "GET":
            environ["HTTP_ORIGIN"] = "http://maverick.test"
        if cookie:
            environ["HTTP_COOKIE"] = cookie

        def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
            headers.update(dict(response_headers))
            headers["__status__"] = status

        body_bytes = b"".join(app(environ, start_response))
        return int(headers["__status__"].split()[0]), json.loads(body_bytes.decode("utf-8")), headers

    def _invoke_raw(
        self,
        app: PlatformHost,
        *,
        path: str,
        method: str = "GET",
        cookie: str | None = None,
    ) -> tuple[int, bytes, dict[str, str]]:
        headers: dict[str, str] = {}
        environ = {
            "PATH_INFO": path,
            "REQUEST_METHOD": method,
            "CONTENT_LENGTH": "0",
            "CONTENT_TYPE": "application/json",
            "QUERY_STRING": "",
            "HTTP_HOST": "maverick.test",
            "wsgi.input": BytesIO(b""),
        }
        if cookie:
            environ["HTTP_COOKIE"] = cookie

        def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
            headers.update(dict(response_headers))
            headers["__status__"] = status

        body_bytes = b"".join(app(environ, start_response))
        return int(headers["__status__"].split()[0]), body_bytes, headers
