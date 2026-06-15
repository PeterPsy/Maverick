"""Compatibility OpenDesign HTTP surface used only when no curated bundle exists.

The Design Studio contract starts ``opendesign_launcher.py``. This module is a
small local fallback so tests and fresh checkouts remain diagnosable before the
real OpenDesign bundle is materialized under ``service/vendor/open-design``.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from urllib.parse import urlparse


OPENDESIGN_VERSION = "0.10.1"
OPENDESIGN_COMMIT = "eb245799adf07e7727ad5f970485d809bad5780e"


class OpenDesignCompatibilityHandler(BaseHTTPRequestHandler):
    server_version = "MaverickOpenDesignCompat/0.2"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/api/health", "/api/ready"}:
            self._json({"status": "ready", "service": "opendesign", "mode": "compatibility-fallback"})
            return
        if parsed.path == "/api/version":
            self._json(
                {
                    "name": "open-design",
                    "version": OPENDESIGN_VERSION,
                    "commit": OPENDESIGN_COMMIT,
                    "mode": "maverick-compatibility-fallback",
                    "technical_token_seen": self._technical_token_seen(),
                    "bundle_configured": False,
                }
            )
            return
        if parsed.path in {"", "/", "/index.html"}:
            self._html(_index_html())
            return
        self._json({"error": "not_found"}, status=404)

    def log_message(self, _format: str, *args: object) -> None:
        return

    def _technical_token_seen(self) -> bool:
        expected = f"Bearer {os.environ.get('OD_API_TOKEN', '')}"
        return bool(os.environ.get("OD_API_TOKEN")) and self.headers.get("Authorization") == expected

    def _json(self, payload: dict[str, object], *, status: int = 200) -> None:
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


def ensure_runtime_dirs() -> Path:
    data_dir = Path(os.environ.get("OD_DATA_DIR") or ".opendesign").resolve()
    media_config_dir = Path(os.environ.get("OD_MEDIA_CONFIG_DIR") or data_dir / "media-config").resolve()
    for relative in ("db", "projects", "temp"):
        (data_dir / relative).mkdir(parents=True, exist_ok=True)
    media_config_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


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
        border-radius: 8px;
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
      <h1>OpenDesign bundle not materialized</h1>
      <p>Design Studio is running the compatibility fallback for OpenDesign <code>{OPENDESIGN_VERSION}</code>. Package the curated daemon under <code>service/vendor/open-design</code> to run the real sidecar.</p>
    </main>
  </body>
</html>"""


def main() -> None:
    host = os.environ.get("OD_BIND_HOST") or "127.0.0.1"
    port = int(os.environ.get("OD_PORT") or "0")
    ensure_runtime_dirs()
    ThreadingHTTPServer((host, port), OpenDesignCompatibilityHandler).serve_forever()


if __name__ == "__main__":
    main()
