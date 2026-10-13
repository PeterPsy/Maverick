"""Loopback-only E2E fixture; never shipped as a Browser app surface."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import asyncio
import json
import html
import mimetypes
import os
from pathlib import Path
import subprocess
import sys
import time
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "apps/browser"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(APP / "backend"))
from service import handle_action, mcp_result_for_tool
from companion_store import database
from core.api.app_frame_browser import _inject_message_relay
from core.api.app_frame_launch import content_security_policy
from core.api.app_frame_background import GRANT_PATH, REQUEST_PATH, handle_background_request
from core.apps.app_background_grants import AppBackgroundGrantStore
from core.apps.sidecar_browser_sessions import SidecarBrowserBinding

TEMPORARY = TemporaryDirectory()
WORKSPACE = Path(TEMPORARY.name)
DEPENDENCIES = {"dependencies": [{"alias": "storage-file-content-write", "status": "resolved", "selected_provider_app_ids": ["storage"]}]}
TICKETS = set()
FRAME_LABEL = "af-0123456789abcdef01234567"
BACKGROUND_GRANTS = AppBackgroundGrantStore()


def storage_request(request):
    data = WORKSPACE / "data/storage"
    generated, uploaded = WORKSPACE / "storage/generated", WORKSPACE / "storage/uploaded"
    for path in (data, generated, uploaded):
        path.mkdir(parents=True, exist_ok=True)
    payload = {"surface": "dependency_backend", "workspace_id": "fixture", "workspace_root": str(WORKSPACE),
               "app_id": "storage", "consumer_app_id": "browser", "dependency_alias": request["dependency_alias"],
               "data_root": str(data), "generated_storage_root": str(generated), "uploaded_storage_root": str(uploaded),
               "user_id": "fixture-user", "workspace_role": "admin", "platform_role": "admin", "effective_mode": "full-access", "body": request["body"]}
    environment = {**os.environ, "PYTHONPATH": str(ROOT)}
    response = subprocess.run([sys.executable, str(ROOT / "apps/storage/backend/app_backend.py")], input=json.dumps(payload),
                              capture_output=True, text=True, cwd=ROOT / "apps/storage", env=environment, timeout=30, check=True)
    return json.loads(response.stdout)


def browser_request(body, surface="backend"):
    status, response = handle_action(WORKSPACE / "data/browser", body, workspace_id="fixture", user_id="fixture-user",
                                   surface=surface, dependencies=DEPENDENCIES)
    for request in response.pop("dependency_backend_requests", []):
        provider = storage_request(request)
        callback = {**request["callback"]["payload"], "action": request["callback"]["action"], "request": request,
                    "request_id": request["request_id"], "dependency_alias": request["dependency_alias"],
                    "dependency_backend_status": "completed" if provider.get("status_code", 500) < 400 else "failed",
                    "dependency_backend_result": provider}
        browser_request(callback,"dependency_backend_request_callback")
    return status, response


def connectors_request(body, surface="backend", depth=0, tool_name=None):
    if depth > 10:
        raise ValueError("Fixture dependency chain exceeded its bound.")
    payload = {"surface":surface,"workspace_id":"fixture","workspace_root":str(WORKSPACE),
               "app_id":"platform-connectors","data_root":str(WORKSPACE / "data/platform-connectors"),
               "user_id":"fixture-user","effective_mode":"full-access","body":body}
    entrypoint = "backend/app_backend.py"
    if tool_name:
        entrypoint = "mcp/server.py"
        payload.update(tool_name=tool_name, arguments=body)
        payload.pop("body")
    process = subprocess.run([sys.executable,str(ROOT / "apps/platform-connectors" / entrypoint)],
                             input=json.dumps(payload),capture_output=True,text=True,cwd=ROOT,
                             env={**os.environ,"PYTHONPATH":str(ROOT)},timeout=30,check=True)
    envelope = json.loads(process.stdout)
    response = envelope if tool_name else envelope["json"]
    for request in response.pop("dependency_backend_requests",[]):
        if request["dependency_alias"] == "browser":
            status,result = browser_request(request["body"],"dependency_backend")
            provider = {"status_code":status,"json":result}
        elif request["dependency_alias"] == "storage":
            provider = storage_request(request)
        else:
            provider = {"status_code":503,"json":{"error":"optional_fixture_provider_unavailable"}}
        callback = {"action":request["callback"]["action"],"request":request,"request_id":request["request_id"],
                    "dependency_alias":request["dependency_alias"],"dependency_backend_status":"completed" if provider["status_code"]<400 else "failed",
                    "dependency_backend_result":provider}
        connectors_request(callback,"dependency_backend_request_callback",depth+1)
    return envelope["status_code"],response


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        isolated = self.headers.get("Host", "").startswith("af-")
        if isolated and self.path not in {"/__test/bootstrap", REQUEST_PATH} and "fixture_frame=authorized" not in self.headers.get("Cookie", ""):
            self.send_error(401); return
        if self.path == "/.well-known/maverick-app-frame-session":
            self.send_response(204); self.end_headers(); return
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 8 * 1024 * 1024:
            self.send_error(413); return
        raw = self.rfile.read(length)
        if self.path in {GRANT_PATH, REQUEST_PATH}:
            self.background_request(raw)
            return
        if self.path == "/__test/login":
            self.send_response(303); self.send_header("Set-Cookie", "fixture_platform=authorized; Path=/; HttpOnly; SameSite=Strict")
            self.send_header("Location", "/app/browser?connector=1"); self.end_headers(); return
        if self.path == "/__test/bootstrap":
            ticket = parse_qs(raw.decode()).get("ticket", [""])[0]
            if not isolated or ticket not in TICKETS:
                self.send_error(403); return
            TICKETS.remove(ticket)
            self.send_response(303); self.send_header("Set-Cookie", "fixture_frame=authorized; Path=/; HttpOnly; SameSite=Strict")
            self.send_header("Location", "/apps/browser/?maverick_theme=light"); self.end_headers(); return
        body = json.loads(raw)
        if self.path == "/api/apps/browser/backend":
            status,response = browser_request(body)
        elif self.path == "/api/apps/platform-connectors/backend":
            status,response = connectors_request(body)
        elif self.path == "/__test/connectors/mcp":
            status,response = connectors_request(body.get("arguments",{}), "mcp", tool_name=body["tool_name"])
        elif self.path == "/__test/browser/mcp":
            status,response = mcp_result_for_tool(WORKSPACE / "data/browser", body["tool_name"], body.get("arguments",{}),
                                                  workspace_id="fixture", user_id="fixture-user", surface="mcp", dependencies=DEPENDENCIES)
        elif self.path == "/__test/browser/expire":
            with database(WORKSPACE / "data/browser") as db:
                db.execute("UPDATE connections SET expires_at=? WHERE session_id=?", (time.time()-1,body["session_id"]))
            status,response = 200,{"expired":True}
        else:
            self.send_error(404); return
        content = json.dumps(response).encode()
        self.send_response(status); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(content))); self.end_headers(); self.wfile.write(content)

    def do_DELETE(self):
        if self.path == REQUEST_PATH:
            self.background_request(b"")
        else:
            self.send_error(404)

    def background_request(self, raw):
        # Exercise the real Core transport, including the extension's actual
        # browser Origin header. Only platform identity validation is a fixture.
        host = self.headers["Host"]
        binding = SidecarBrowserBinding("fixture-user", "fixture", "browser", "frame", host, f"http://{host}", f"http://maverick.localhost:{self.server.server_port}", "fixture", "login", "/apps/browser/", False, "", platform_session_id="login")
        scope = {"path": self.path, "method": self.command, "headers": [(key.lower().encode(), value.encode()) for key, value in self.headers.items()]}
        messages = []
        async def receive():
            return {"type": "http.request", "body": raw, "more_body": False}
        async def send(message):
            messages.append(message)
        async def send_json(_send, body, *, status, headers):
            await send({"type": "http.response.start", "status": status, "headers": [(key.lower().encode(), value.encode()) for key, value in headers] + [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": json.dumps(body).encode()})
        async def validate(_state, **_kwargs):
            return ("fixture", SimpleNamespace(binding=binding))
        async def forward(transformed, _receive, response_send):
            assert transformed["path"] == "/api/apps/browser/backend"
            status, response = browser_request(json.loads(raw))
            await response_send({"type": "http.response.start", "status": status, "headers": [(b"content-type", b"application/json")]})
            await response_send({"type": "http.response.body", "body": json.dumps(response).encode()})
        asyncio.run(handle_background_request(SimpleNamespace(app_background_grants=BACKGROUND_GRANTS), scope=scope, receive=receive, send=send, host=host, start_path=ROOT, forward=forward, validate_session=validate, current_frame=lambda *_args, **_kwargs: True, platform_scope=lambda selected, _session, **_kwargs: {**selected}, send_json=send_json))
        started = messages[0]
        content = b"".join(message.get("body", b"") for message in messages[1:])
        self.send_response(started["status"])
        for key, value in started["headers"]:
            self.send_header(key.decode(), value.decode())
        self.send_header("Content-Length", str(len(content))); self.end_headers(); self.wfile.write(content)

    def do_GET(self):
        parsed = urlsplit(self.path)
        isolated = self.headers.get("Host", "").startswith("af-")
        origin = f"http://maverick.localhost:{self.server.server_port}"
        frame_origin = f"http://{FRAME_LABEL}.sidecars.maverick.localhost:{self.server.server_port}"
        if parsed.path in {"/app/browser", "/__test/download"}:
            if parsed.path == "/__test/download":
                archive = next((APP / "frontend/dist/assets").glob("maverick-browser-companion-*.zip"))
                body = f'<a href="/apps/browser/assets/{archive.name}" download="maverick-browser-companion.zip">Download Companion</a>'
            elif "fixture_platform=authorized" not in self.headers.get("Cookie", ""):
                body = '<h1>Sign in to Maverick</h1><form action="/__test/login" method="post"><input type="hidden" name="fixture" value="1"><button>Sign in as fixture user</button></form>'
            else:
                ticket = uuid4().hex; TICKETS.add(ticket)
                bootstrap = f'<form method="post" action="{frame_origin}/__test/bootstrap"><input type="hidden" name="ticket" value="{ticket}"></form><script>document.querySelector("form").submit()</script>'
                body = f'<iframe id="browser" title="Browser" sandbox="allow-downloads allow-forms allow-popups allow-popups-to-escape-sandbox allow-same-origin allow-scripts" srcdoc="{html.escape(bootstrap, quote=True)}" style="border:0;width:100%;height:100vh"></iframe><script>document.querySelector("iframe").addEventListener("load",()=>document.querySelector("iframe").contentWindow.postMessage({{type:"maverick.app.navigate",app_id:"browser",params:{{connector:"1"}}}},"{frame_origin}"));</script>'
            content = f'<!doctype html><html><head><title>Maverick fixture</title></head><body style="margin:0">{body}</body></html>'.encode()
            self.send_response(200); self.send_header("Content-Type", "text/html"); self.send_header("Content-Length", str(len(content)))
            self.end_headers(); self.wfile.write(content); return
        if parsed.path.startswith("/apps/browser/") and not parsed.path.startswith("/apps/browser/assets/"):
            if not isolated:
                self.send_error(403, "app_frame_isolation_required"); return
            if "fixture_frame=authorized" not in self.headers.get("Cookie", ""):
                self.send_error(401); return
        if parsed.path == "/__test/media":
            operation_id = parse_qs(parsed.query).get("operation_id", [""])[0]
            status, operation = handle_action(WORKSPACE / "data/browser", {"action": "operation.get", "operation_id": operation_id}, workspace_id="fixture", user_id="fixture-user", surface="backend")
            if status >= 400:
                self.send_error(404); return
            relative = operation["result"]["audio"]["storage"]["workspace_relative_path"]
            path = (WORKSPACE / relative).resolve()
            if (WORKSPACE / "storage/generated").resolve() not in path.parents:
                self.send_error(403); return
            content = path.read_bytes(); self.send_response(200); self.send_header("Content-Type", "audio/webm"); self.send_header("Content-Length", str(len(content))); self.end_headers(); self.wfile.write(content); return
        if parsed.path.startswith("/storage/generated/"):
            root = (WORKSPACE / "storage/generated").resolve()
            relative = parsed.path.removeprefix("/storage/generated/")
        elif parsed.path.startswith("/apps/platform-connectors/"):
            self.send_error(404); return
        else:
            root = (APP / "frontend/dist").resolve()
            relative = parsed.path.removeprefix("/apps/browser/") or "index.html"
        path = (root / relative).resolve()
        if root not in path.parents or not path.is_file():
            self.send_error(404); return
        content = path.read_bytes()
        if path.suffix == ".html":
            # Use the platform's actual immutable app identity and message relay.
            content = _inject_message_relay(content, SimpleNamespace(platform_origin=origin,
                parent_origin=origin, mount_app_id="browser", app_id="browser", workspace_id="fixture", widget_id=None))
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", frame_origin)
        if isolated and path.suffix == ".html":
            self.send_header("Content-Security-Policy", content_security_policy(origin))
        self.send_header("Content-Type", mimetypes.guess_type(path)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(content))); self.end_headers(); self.wfile.write(content)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    print(json.dumps({"port": server.server_port}), flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close(); TEMPORARY.cleanup()
