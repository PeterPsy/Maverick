"""Independent rescue HTTP surface for Maverick v3."""

from __future__ import annotations

import json
from typing import Callable, Iterable

StartResponse = Callable[[str, list[tuple[str, str]]], None]


def _respond(start_response: StartResponse, body: bytes, *, status: str, content_type: str) -> list[bytes]:
    start_response(status, [("Content-Type", content_type), ("Content-Length", str(len(body)))])
    return [body]


class RescueHost:
    """Serve the rescue entrypoint independently from the main core host."""

    def __call__(self, environ: dict, start_response: StartResponse) -> Iterable[bytes]:
        path = environ.get("PATH_INFO", "/")
        if path == "/health":
            return _respond(
                start_response,
                json.dumps({"status": "ok", "service": "maverick3-rescue"}).encode("utf-8"),
                status="200 OK",
                content_type="application/json; charset=utf-8",
            )
        html = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Maverick v3 Rescue</title>
    <style>
      body { margin: 0; font-family: Georgia, serif; background: #1f2428; color: #f3efe6; }
      main { max-width: 760px; margin: 0 auto; padding: 48px 24px; }
      article { border: 1px solid rgba(255,255,255,0.16); border-radius: 20px; padding: 24px; background: rgba(255,255,255,0.04); }
      a { color: #9de6dd; }
    </style>
  </head>
  <body>
    <main>
      <article>
        <h1>Maverick v3 Rescue</h1>
        <p>This rescue service runs independently from the main core host.</p>
        <p>Use it when the main platform backend is degraded and you still need an operational recovery entrypoint.</p>
        <p><a href="/health">Health JSON</a></p>
      </article>
    </main>
  </body>
</html>"""
        return _respond(start_response, html.encode("utf-8"), status="200 OK", content_type="text/html; charset=utf-8")
