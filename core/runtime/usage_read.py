"""Transcript-authorized usage reads for runtime CLI/MCP diagnostics."""

from core.runtime.errors import RuntimeTranscriptAccessError, RuntimeTranscriptValidationError
from core.runtime.transcript_access import resolve_authorized_transcript_thread
from core.usage.payloads import runtime_usage_diagnostic_payload
from core.usage.service import build_runtime_chat_usage_summary, summarize_samples


def read_runtime_usage(runtime_store, *, usage_store, context, thread_id, turn_id=None):
    thread, session, _relation = resolve_authorized_transcript_thread(runtime_store, context=context, thread_id=thread_id)
    if usage_store is None:
        raise RuntimeTranscriptAccessError("runtime_usage_unavailable", status_code=503)
    if turn_id is not None:
        if not any(turn.turn_id == turn_id for turn in runtime_store.list_turns(session.session_id)):
            raise RuntimeTranscriptValidationError("runtime_usage_turn_not_found")
        samples = [sample for sample in usage_store.list_samples(workspace_id=session.workspace_id,
                   session_id=session.session_id) if sample.turn_id == turn_id]
        summary = summarize_samples(samples, workspace_id=session.workspace_id,
                    root_session_id=session.session_id, direct_session_ids={session.session_id})
    else:
        summary = build_runtime_chat_usage_summary(usage_store, runtime_store=runtime_store, session=session)
    return {"thread_id": thread.thread_id, "turn_id": turn_id,
            "scope": "direct_turn" if turn_id is not None else "root_chat_with_delegation",
            "usage": runtime_usage_diagnostic_payload(summary)}
