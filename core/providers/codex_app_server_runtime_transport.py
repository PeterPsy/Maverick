"""Concurrent JSON-RPC request transport for Codex app-server."""

from __future__ import annotations

import json
import queue
from typing import Any, Callable

from core.providers.codex_app_server_runtime_errors import (
    CodexAppServerDeliveryUncertainError,
    CodexAppServerRequestError,
)
from core.providers.codex_app_server_runtime_state import _CodexAppServerRuntime


def _send_request(
    runtime: _CodexAppServerRuntime,
    method: str,
    params: dict[str, Any],
    *,
    timeout: float,
    on_sent: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, Any]:
    with runtime.request_lock:
        request_id = runtime.next_request_id
        runtime.next_request_id += 1
        waiter: queue.Queue = queue.Queue(maxsize=1)
        runtime.response_waiters[request_id] = waiter
    payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
    try:
        if runtime.process.stdin is None:
            raise RuntimeError("Codex app-server stdin is unavailable.")
        with runtime.write_lock:
            runtime.process.stdin.write(json.dumps(payload) + "\n")
            runtime.process.stdin.flush()
        if on_sent is not None:
            on_sent({"request_id": request_id})
    except Exception as error:
        with runtime.request_lock:
            runtime.response_waiters.pop(request_id, None)
        raise CodexAppServerDeliveryUncertainError(
            f"Failed to send `{method}` to Codex app-server; delivery is uncertain: {error}"
        ) from error

    try:
        response = waiter.get(timeout=timeout)
    except queue.Empty as error:
        with runtime.request_lock:
            runtime.response_waiters.pop(request_id, None)
        raise CodexAppServerDeliveryUncertainError(
            f"`{method}` timed out against Codex app-server; delivery is uncertain."
        ) from error
    if isinstance(response, dict) and response.get("_transport_error"):
        raise CodexAppServerDeliveryUncertainError(str(response["_transport_error"]))
    if isinstance(response, dict) and "error" in response:
        detail = response.get("error")
        message = str(detail.get("message") or "request rejected") if isinstance(detail, dict) else str(detail)
        raw_code = detail.get("code") if isinstance(detail, dict) else None
        code = raw_code if isinstance(raw_code, int) else None
        data = detail.get("data") if isinstance(detail, dict) else None
        raise CodexAppServerRequestError(method, code=code, message=message, data=data)
    result = response.get("result") if isinstance(response, dict) else None
    return result if isinstance(result, dict) else {}
