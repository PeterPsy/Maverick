"""Fail-closed thread resolution for transcript services."""

from __future__ import annotations

from core.authorization.errors import AuthorizationError
from core.authorization.service import require_runtime_transcript_read_context
from core.runtime.errors import (
    RuntimeSessionNotFoundError,
    RuntimeThreadNotFoundError,
    RuntimeTranscriptAccessError,
    RuntimeTranscriptValidationError,
)
from core.runtime.store import RuntimeStore
from core.runtime.transcript_models import RuntimeTranscriptReadContext


def resolve_authorized_transcript_thread(
    store: RuntimeStore,
    *,
    context: RuntimeTranscriptReadContext,
    thread_id: str,
):
    """Resolve one visible same-workspace thread and its access relation."""
    normalized_thread_id = str(thread_id or "").strip()
    if not normalized_thread_id:
        raise RuntimeTranscriptValidationError("thread_id_required")
    try:
        thread = store.get_thread(normalized_thread_id)
    except RuntimeThreadNotFoundError as error:
        raise RuntimeTranscriptAccessError("runtime_thread_not_found", status_code=404) from error
    if thread.workspace_id != context.workspace_id or not thread.runtime_session_id:
        raise RuntimeTranscriptAccessError("runtime_thread_not_found", status_code=404)
    try:
        session = store.get_session(thread.runtime_session_id)
    except (RuntimeSessionNotFoundError, ValueError) as error:
        raise RuntimeTranscriptAccessError("runtime_thread_not_found", status_code=404) from error
    if session.workspace_id != thread.workspace_id:
        raise RuntimeTranscriptAccessError("runtime_thread_not_found", status_code=404)
    relation = transcript_authorization_relation(session, context)
    return thread, session, relation


def transcript_authorization_relation(session, context: RuntimeTranscriptReadContext) -> str:
    """Translate authorization-domain reasons to transcript surface errors."""
    try:
        return require_runtime_transcript_read_context(
            session=session,
            workspace_id=context.workspace_id,
            user_id=context.user_id,
            platform_role=context.platform_role,
            workspace_role=context.workspace_role,
            caller_runtime_session_id=context.caller_runtime_session_id,
        )
    except AuthorizationError as error:
        status_code = 404 if error.reason == "runtime_thread_not_found" else 403
        raise RuntimeTranscriptAccessError(error.reason, status_code=status_code) from error
