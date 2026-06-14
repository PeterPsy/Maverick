"""Small OpenDesign-compatible sidecar stub for the Maverick MVP.

The production integration replaces this file with the pinned OpenDesign daemon.
It intentionally exposes only sandbox-safe routes covered by the app contract.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from urllib.parse import urlparse


OPENDESIGN_VERSION = "0.10.1"
OPENDESIGN_COMMIT = "eb245799adf07e7727ad5f970485d809bad5780e"


class OpenDesignStubHandler(BaseHTTPRequestHandler):
    server_version = "MaverickOpenDesignStub/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/api/health", "/api/ready"}:
            self._json({"status": "ready", "service": "opendesign", "mode": "stub"})
            return
        if parsed.path == "/api/version":
            self._json(
                {
                    "name": "open-design",
                    "version": OPENDESIGN_VERSION,
                    "commit": OPENDESIGN_COMMIT,
                    "mode": "maverick-governed-stub",
                    "technical_token_seen": self._technical_token_seen(),
                }
            )
            return
        if parsed.path == "/api/projects":
            self._json({"projects": _project_index()})
            return
        if parsed.path in {"", "/"}:
            self._html(_index_html())
            return
        self._json({"error": "not_found"}, status=404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/projects":
            body = self.rfile.read(int(self.headers.get("Content-Length", "0") or "0"))
            try:
                payload = json.loads(body.decode("utf-8") or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError):
                payload = {}
            name = str(payload.get("name") or "OpenDesign project").strip()[:120]
            project = {"id": f"od_{len(_project_index()) + 1}", "name": name, "status": "created"}
            _write_project(project)
            self._json({"project": project}, status=201)
            return
        self._json({"error": "not_found"}, status=404)

    def log_message(self, format: str, *args) -> None:
        return

    def _technical_token_seen(self) -> bool:
        expected = f"Bearer {os.environ.get('OD_API_TOKEN', '')}"
        return bool(os.environ.get("OD_API_TOKEN")) and self.headers.get("Authorization") == expected

    def _json(self, payload: dict, *, status: int = 200) -> None:
        body = json.dumps(payload, indent=2, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, body: str, *, status: int = 200) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def _project_index() -> list[dict]:
    path = _data_dir() / "projects.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return payload if isinstance(payload, list) else []


def _write_project(project: dict) -> None:
    projects = _project_index()
    projects.append(project)
    path = _data_dir() / "projects.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(projects, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _data_dir() -> Path:
    path = Path(os.environ.get("OD_DATA_DIR") or ".opendesign").resolve()
    path.mkdir(parents=True, exist_ok=True)
    Path(os.environ.get("OD_MEDIA_CONFIG_DIR") or path / "media-config").mkdir(parents=True, exist_ok=True)
    return path


def _index_html() -> str:
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>OpenDesign Sidecar</title>
    <style>
      :root {{
        color-scheme: dark;
        font-family: "Avenir Next", "Segoe UI", Inter, sans-serif;
        background: #08090a;
        color: #ececec;
      }}
      body {{
        margin: 0;
        min-height: 100vh;
        display: grid;
        place-items: center;
        background: #08090a;
      }}
      main {{
        width: min(720px, calc(100% - 48px));
        border: 1px solid rgba(255,255,255,.1);
        border-radius: 22px;
        background: rgba(255,255,255,.055);
        padding: 24px;
      }}
      h1 {{
        margin: 0 0 10px;
        font-size: 24px;
        font-weight: 600;
        letter-spacing: 0;
      }}
      p {{
        margin: 0;
        color: rgba(236,236,236,.68);
        line-height: 1.5;
      }}
      code {{
        color: #9ff0ca;
      }}
    </style>
  </head>
  <body>
    <main>
      <h1>OpenDesign sidecar ready</h1>
      <p>Maverick is proxying a governed sidecar surface pinned to OpenDesign <code>{OPENDESIGN_VERSION}</code>. Native terminal and host-folder import routes are blocked in sandbox mode.</p>
    </main>
  </body>
</html>"""


def main() -> None:
    host = os.environ.get("OD_BIND_HOST") or "127.0.0.1"
    port = int(os.environ.get("OD_PORT") or "0")
    _data_dir()
    ThreadingHTTPServer((host, port), OpenDesignStubHandler).serve_forever()


if __name__ == "__main__":
    main()
