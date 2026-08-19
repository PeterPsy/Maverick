"""App-owned metadata cleanup invoked by the core runtime lifecycle."""

from __future__ import annotations

from io import BytesIO
import json

from core.api.app_mounts import handle_app_backend
from core.api.platform_state import PlatformState
from core.api.runtime_cleanup_errors import RuntimeCleanupError


def cleanup_app_runtime_session_metadata(
    state: PlatformState,
    *,
    workspace_id: str,
    session_ids: list[str],
    start_path,
) -> list[dict[str, object]]:
    """Invoke each eligible app backend once for a deduplicated session batch."""
    normalized_session_ids = list(dict.fromkeys(item.strip() for item in session_ids if item.strip()))
    if not normalized_session_ids:
        return []
    cleanup_results: list[dict[str, object]] = []
    for binding in state.app_store.list_workspace_app_bindings(workspace_id):
        if binding.status != "enabled":
            continue
        from core.api.app_registry import resolve_app_surface

        try:
            _binding, _source_root, parsed = resolve_app_surface(
                state,
                workspace_id=workspace_id,
                app_id=binding.app_id,
                start_path=start_path,
            )
        except Exception:
            continue
        if (
            not parsed.contract.permissions.runtime.receive_cleanup_callbacks
            or parsed.contract.entrypoints.backend is None
        ):
            continue
        result = _invoke_runtime_cleanup_backend(
            state,
            workspace_id=workspace_id,
            app_id=binding.app_id,
            session_ids=normalized_session_ids,
            start_path=start_path,
        )
        cleanup_results.append({"app_id": binding.app_id, **result})
    return cleanup_results


def _invoke_runtime_cleanup_backend(
    state: PlatformState,
    *,
    workspace_id: str,
    app_id: str,
    session_ids: list[str],
    start_path,
) -> dict[str, object]:
    body = {"action": "runtime.cleanup_sessions", "runtime_session_ids": session_ids}
    payload_bytes = json.dumps(body).encode("utf-8")
    headers: dict[str, str] = {}
    environ = {
        "PATH_INFO": f"/api/apps/{app_id}/backend",
        "REQUEST_METHOD": "POST",
        "CONTENT_LENGTH": str(len(payload_bytes)),
        "CONTENT_TYPE": "application/json",
        "QUERY_STRING": "",
        "wsgi.input": BytesIO(payload_bytes),
    }

    def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
        headers.update(dict(response_headers))
        headers["__status__"] = status

    response_body = b"".join(
        handle_app_backend(
            state,
            environ=environ,
            workspace_id=workspace_id,
            app_id=app_id,
            user=None,
            start_path=start_path,
            start_response=start_response,
            trusted_platform_invocation=True,
        )
    )
    status_code = int(headers.get("__status__", "500 Internal Server Error").split()[0])
    payload = json.loads(response_body.decode("utf-8")) if response_body else {}
    if status_code >= 400:
        detail = str(payload.get("error") or "app_runtime_cleanup_failed")
        raise RuntimeCleanupError(
            f"Failed to clean app `{app_id}` records for runtime sessions "
            f"`{', '.join(session_ids)}`: {detail}"
        )
    return payload if isinstance(payload, dict) else {}
