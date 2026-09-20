"""Sequential, stateless JSON request protocol for explicitly reusable app workers."""

from collections.abc import Callable
import json
import sys
from typing import Any

from core.shared.entrypoints import JSON_WORKER_MESSAGE_MAX_BYTES as MAX_MESSAGE_BYTES


def serve_json_requests(handler: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
    """Serve one JSON object per line until EOF; handler exceptions end the worker.

    Handlers must use only the current payload for identity, grants and secrets.
    Keep stdout reserved for this protocol and do not retain per-request state.
    Streaming media must continue to use the ordinary backend entrypoint.
    """
    while raw := sys.stdin.buffer.readline(MAX_MESSAGE_BYTES + 1):
        if len(raw) > MAX_MESSAGE_BYTES or not raw.endswith(b"\n"):
            raise ValueError("JSON worker request exceeds its framing limit.")
        envelope = json.loads(raw)
        request_id = envelope.get("request_id") if isinstance(envelope, dict) else None
        payload = envelope.get("payload") if isinstance(envelope, dict) else None
        if not isinstance(request_id, str) or not request_id or len(request_id) > 64 or not isinstance(payload, dict):
            raise ValueError("JSON worker requests must be objects.")
        result = handler(payload)
        if not isinstance(result, dict):
            raise ValueError("JSON worker responses must be objects.")
        response = json.dumps({"request_id": request_id, "result": result}, ensure_ascii=True, separators=(",", ":")).encode() + b"\n"
        if len(response) > MAX_MESSAGE_BYTES:
            raise ValueError("JSON worker response exceeds its framing limit.")
        sys.stdout.buffer.write(response)
        sys.stdout.buffer.flush()
        del envelope, payload, result, response, raw, request_id
