"""Platform-level runtime cleanup helpers for shell and app APIs."""

from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import shutil

from core.api.app_mounts import handle_app_backend
from core.api.platform_state import PlatformState
from core.runtime.errors import RuntimeSessionNotFoundError
from core.runtime.session_termination import terminate_runtime_session


class RuntimeCleanupError(Exception):
    """Raised when one full runtime cleanup cannot complete."""


def cleanup_runtime_session(
    state: PlatformState,
    *,
    session_id: str,
    reason: str,
    start_path=None,
) -> dict[str, object]:
    """Fully remove one runtime session, its chat thread metadata, and runtime files."""
    try:
        session = state.runtime_store.get_session(session_id)
    except RuntimeSessionNotFoundError:
        return {
            "session_id": session_id,
            "found": False,
            "workspace_id": None,
            "terminated_processes": 0,
            "cancelled_turns": 0,
            "deleted": {"sessions": 0, "turns": 0, "events": 0, "processes": 0, "states": 0},
            "deleted_threads": 0,
            "deleted_thread_ids": [],
            "runtime_root_deleted": False,
        }

    chat_cleanup = _cleanup_chat_threads_for_runtime_session(
        state,
        workspace_id=session.workspace_id,
        session_id=session.session_id,
        start_path=start_path or state.repository_root,
    )
    termination = terminate_runtime_session(
        state.runtime_store,
        session_id=session.session_id,
        reason=reason,
        event_bus=state.runtime_event_bus,
        observability_store=state.observability_store,
        start_path=start_path or state.repository_root,
    )
    deleted = state.runtime_store.delete_session_records(session.session_id)
    runtime_root_deleted = _delete_runtime_root(Path(session.runtime_root))
    return {
        **termination,
        "workspace_id": session.workspace_id,
        "deleted": deleted,
        "deleted_threads": int(chat_cleanup.get("deleted_threads") or 0),
        "deleted_thread_ids": list(chat_cleanup.get("deleted_thread_ids") or []),
        "runtime_root_deleted": runtime_root_deleted,
    }


def _cleanup_chat_threads_for_runtime_session(
    state: PlatformState,
    *,
    workspace_id: str,
    session_id: str,
    start_path,
) -> dict[str, object]:
    body = {"action": "threads.cleanup_runtime_sessions", "runtime_session_ids": [session_id]}
    payload = json.dumps(body).encode("utf-8")
    headers: dict[str, str] = {}
    environ = {
        "PATH_INFO": "/api/apps/chat/backend",
        "REQUEST_METHOD": "POST",
        "CONTENT_LENGTH": str(len(payload)),
        "CONTENT_TYPE": "application/json",
        "QUERY_STRING": "",
        "wsgi.input": BytesIO(payload),
    }

    def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
        headers.update(dict(response_headers))
        headers["__status__"] = status

    response_body = b"".join(
        handle_app_backend(
            state,
            environ=environ,
            workspace_id=workspace_id,
            app_id="chat",
            user=None,
            start_path=start_path,
            start_response=start_response,
        )
    )
    status_code = int(headers.get("__status__", "500 Internal Server Error").split()[0])
    payload = json.loads(response_body.decode("utf-8")) if response_body else {}
    if status_code >= 400:
        detail = str(payload.get("error") or "chat_runtime_cleanup_failed")
        raise RuntimeCleanupError(f"Failed to clean chat records for runtime session `{session_id}`: {detail}")
    return payload if isinstance(payload, dict) else {}


def _delete_runtime_root(runtime_root: Path) -> bool:
    if not runtime_root.exists():
        return False
    shutil.rmtree(runtime_root)
    return True
