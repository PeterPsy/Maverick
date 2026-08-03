"""Process fixture shared by governed sidecar proxy integration tests."""

import textwrap


TEST_SIDECAR_SERVER = textwrap.dedent(
    """
    from __future__ import annotations

    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import json
    import os
    import time


    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/api/ready"):
                self._json({"status": "ready"})
                return
            if self.path.startswith("/api/version"):
                expected = "Bearer " + os.environ.get("OD_API_TOKEN", "")
                self._json({
                    "service": "opendesign-test",
                    "technical_token_seen": self.headers.get("Authorization") == expected,
                    "cookie_seen": bool(self.headers.get("Cookie")),
                    "safe_header": self.headers.get("X-Test", ""),
                })
                return
            if self.path.startswith("/api/events"):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(b"data: one\\n\\n")
                self.wfile.flush()
                time.sleep(0.35)
                self.wfile.write(b"data: two\\n\\n")
                self.wfile.flush()
                return
            if self.path.startswith("/api/import/folder"):
                self._json({"blocked": False})
                return
            self._json({"path": self.path}, status=404)

        def do_POST(self):
            if self.path.startswith("/api/upload"):
                expected = "Bearer " + os.environ.get("OD_API_TOKEN", "")
                remaining = int(self.headers.get("Content-Length", "0"))
                total = 0
                while remaining > 0:
                    chunk = self.rfile.read(min(11, remaining))
                    if not chunk:
                        break
                    total += len(chunk)
                    remaining -= len(chunk)
                self._json({
                    "bytes_read": total,
                    "technical_token_seen": self.headers.get("Authorization") == expected,
                })
                return
            if self.path.startswith("/api/chunked-upload"):
                total = self._read_chunked_body()
                self._json({
                    "bytes_read": total,
                    "chunked": self.headers.get("Transfer-Encoding", "").lower() == "chunked",
                })
                return
            self._json({"path": self.path}, status=404)

        def log_message(self, format, *args):
            return

        def _json(self, payload, status=200):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Set-Cookie", "upstream=must-not-cross")
            self.end_headers()
            self.wfile.write(body)

        def _read_chunked_body(self):
            total = 0
            while True:
                size_line = self.rfile.readline().strip().split(b";", 1)[0]
                if not size_line:
                    return total
                size = int(size_line, 16)
                if size == 0:
                    while self.rfile.readline() not in (b"\\r\\n", b"\\n", b""):
                        pass
                    return total
                remaining = size
                while remaining > 0:
                    chunk = self.rfile.read(remaining)
                    if not chunk:
                        return total
                    total += len(chunk)
                    remaining -= len(chunk)
                self.rfile.read(2)


    host = os.environ["OD_BIND_HOST"]
    port = int(os.environ["OD_PORT"])
    ThreadingHTTPServer((host, port), Handler).serve_forever()
    """
)
