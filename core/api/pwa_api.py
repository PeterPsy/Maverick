"""Public, non-authoritative configuration surface for the PWA lifecycle."""

from __future__ import annotations

from collections.abc import Mapping

from core.api.http import StartResponse, json_response
from core.pwa.feature_flags import public_pwa_config


PWA_CONFIG_PATH = "/api/pwa/config"


def handle_pwa_api(
    environ: dict,
    start_response: StartResponse,
    *,
    environment: Mapping[str, str] | None = None,
) -> list[bytes] | None:
    """Serve the public registration kill switch without session-derived state."""
    if str(environ.get("PATH_INFO") or "") != PWA_CONFIG_PATH:
        return None
    method = str(environ.get("REQUEST_METHOD") or "GET").upper()
    if method != "GET":
        return json_response(
            start_response,
            {"error": "method_not_allowed"},
            status="405 Method Not Allowed",
            headers=[("Allow", "GET")],
        )
    return json_response(
        start_response,
        public_pwa_config(environment=environment),
        headers=[("Cache-Control", "no-store")],
    )
