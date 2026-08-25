#!/usr/bin/env python3
"""Small in-memory OpenDesign HTTP contract double for PlatformHost tests."""

from __future__ import annotations

from base64 import b64decode, b64encode
from io import BytesIO
import json
import os
from urllib.parse import unquote, urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


PROJECTS: dict[str, dict] = {}
FILES: dict[str, dict[str, bytes]] = {}
STATE_PATH = os.path.join(os.environ.get("MAVERICK_OPENDESIGN_DATA_ROOT", "/tmp"), "contract-double-state.json")


def load_state() -> None:
    try:
        payload = json.loads(open(STATE_PATH, encoding="utf-8").read())
    except (OSError, json.JSONDecodeError):
        return
    PROJECTS.update(payload.get("projects") or {})
    FILES.update(
        {
            project_id: {name: b64decode(content) for name, content in files.items()}
            for project_id, files in (payload.get("files") or {}).items()
        }
    )


def save_state() -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    payload = {
        "projects": PROJECTS,
        "files": {
            project_id: {name: b64encode(content).decode("ascii") for name, content in files.items()}
            for project_id, files in FILES.items()
        },
    }
    with open(STATE_PATH, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, _format: str, *_args) -> None:
        return

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path in {"/api/ready", "/api/maverick-ready", "/api/health"}:
            return self._json(200, {"ready": True})
        if path == "/api/version":
            return self._json(200, {"version": "0.16.1"})
        if path == "/api/projects":
            return self._json(200, {"projects": list(PROJECTS.values())})
        parts = [unquote(part) for part in path.split("/") if part]
        if len(parts) == 3 and parts[:2] == ["api", "projects"]:
            project = PROJECTS.get(parts[2])
            return self._json(200, {"project": project}) if project else self._json(404, {"error": "not found"})
        if len(parts) == 4 and parts[:2] == ["api", "projects"] and parts[3] == "files":
            files = [
                {"name": name, "path": name, "size": len(content), "mime": "application/octet-stream"}
                for name, content in sorted(FILES.get(parts[2], {}).items())
            ]
            return self._json(200, {"files": files})
        if len(parts) == 5 and parts[:2] == ["api", "projects"] and parts[3] == "raw":
            content = FILES.get(parts[2], {}).get(parts[4])
            return self._bytes(200, content) if content is not None else self._json(404, {"error": "not found"})
        return self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        body = self._body()
        if path == "/api/projects":
            project_id = str(body.get("id") or "")
            project = {"id": project_id, "name": str(body.get("name") or project_id), "metadata": body.get("metadata") or {}}
            PROJECTS[project_id] = project
            FILES.setdefault(project_id, {})
            save_state()
            return self._json(200, {"project": project})
        parts = [unquote(part) for part in path.split("/") if part]
        if len(parts) == 4 and parts[:2] == ["api", "projects"] and parts[3] == "files":
            project_id = parts[2]
            content = b64decode(str(body.get("content") or "")) if body.get("encoding") == "base64" else str(body.get("content") or "").encode()
            name = str(body.get("name") or "")
            FILES.setdefault(project_id, {})[name] = content
            save_state()
            return self._json(200, {"file": {"name": name, "path": name, "size": len(content)}})
        if len(parts) == 5 and parts[:2] == ["api", "projects"] and parts[3:] == ["archive", "batch"]:
            output = BytesIO()
            with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
                for name in body.get("files", []):
                    info = ZipInfo(str(name), date_time=(1980, 1, 1, 0, 0, 0))
                    info.compress_type = ZIP_DEFLATED
                    archive.writestr(info, FILES.get(parts[2], {}).get(str(name), b""))
            return self._bytes(200, output.getvalue(), media_type="application/zip")
        return self._json(404, {"error": "not found"})

    def _body(self) -> dict:
        length = int(self.headers.get("content-length") or 0)
        try:
            value = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    def _json(self, status: int, payload: dict) -> None:
        self._bytes(status, json.dumps(payload).encode(), media_type="application/json")

    def _bytes(self, status: int, payload: bytes, *, media_type: str = "application/octet-stream") -> None:
        self.send_response(status)
        self.send_header("content-type", media_type)
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


load_state()
ThreadingHTTPServer(
    (os.environ.get("OD_BIND_HOST", "127.0.0.1"), int(os.environ["OD_PORT"])),
    Handler,
).serve_forever()
