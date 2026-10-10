"""Loopback-only E2E fixture; never shipped as a Browser app surface."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "apps/browser"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(APP / "backend"))
from service import handle_action

TEMPORARY = TemporaryDirectory()
WORKSPACE = Path(TEMPORARY.name)
DEPENDENCIES = {"dependencies": [{"alias": "storage-file-content-write", "status": "resolved", "selected_provider_app_ids": ["storage"]}]}


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


def connectors_request(body, surface="backend", depth=0):
    if depth > 10:
        raise ValueError("Fixture dependency chain exceeded its bound.")
    payload = {"surface":surface,"workspace_id":"fixture","workspace_root":str(WORKSPACE),
               "app_id":"platform-connectors","data_root":str(WORKSPACE / "data/platform-connectors"),
               "user_id":"fixture-user","effective_mode":"full-access","body":body}
    process = subprocess.run([sys.executable,str(ROOT / "apps/platform-connectors/backend/app_backend.py")],
                             input=json.dumps(payload),capture_output=True,text=True,cwd=ROOT,
                             env={**os.environ,"PYTHONPATH":str(ROOT)},timeout=30,check=True)
    envelope = json.loads(process.stdout)
    response = envelope["json"]
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
        if self.path == "/.well-known/maverick-app-frame-session":
            self.send_response(204); self.end_headers(); return
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 8 * 1024 * 1024:
            self.send_error(413); return
        body = json.loads(self.rfile.read(length))
        if self.path == "/api/apps/browser/backend":
            status,response = browser_request(body)
        elif self.path == "/api/apps/platform-connectors/backend":
            status,response = connectors_request(body)
        else:
            self.send_error(404); return
        content = json.dumps(response).encode()
        self.send_response(status); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(content))); self.end_headers(); self.wfile.write(content)

    def do_GET(self):
        parsed = urlsplit(self.path)
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
            root = (ROOT / "apps/platform-connectors/frontend/dist").resolve()
            relative = parsed.path.removeprefix("/apps/platform-connectors/") or "index.html"
        else:
            root = (APP / "frontend/dist").resolve()
            relative = parsed.path.removeprefix("/apps/browser/") or "index.html"
        path = (root / relative).resolve()
        if root not in path.parents or not path.is_file():
            self.send_error(404); return
        content = path.read_bytes(); self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(path)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(content))); self.end_headers(); self.wfile.write(content)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    print(json.dumps({"port": server.server_port}), flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close(); TEMPORARY.cleanup()
