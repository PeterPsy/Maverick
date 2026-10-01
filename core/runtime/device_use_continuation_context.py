"""Safe textual context for the first turn after explicit native reconnection."""

import json

from core.runtime.transcript_history import read_runtime_event_history
from core.runtime.transcript_projection import project_runtime_transcript
from core.runtime.transcript_safety import redact_transcript_text


MAX_CONTINUATION_CHARACTERS = 64_000
MAX_CONTINUATION_MESSAGES = 32


def device_use_continuation_context(state, *, session, turn_id: str):
    """Restore conversation text once per lease, never tool calls or receipts."""
    binding = getattr(session, "device_use_binding", None)
    if binding is None:
        return None
    turns = state.runtime_store.list_turns(session.session_id)
    previous = [turn for turn in turns if turn.turn_id != turn_id]
    if not previous or any(
        turn.status == "completed" and turn.created_at >= binding.created_at
        for turn in previous
    ):
        return None
    history = read_runtime_event_history(state.runtime_store, session.session_id)
    messages = project_runtime_transcript(
        history.events, previous, include_turn_status_fallbacks=False,
    ).messages
    visible = [message for message in messages
               if message.role in {"human", "agent"} and message.turn_id != turn_id]
    # Keep the original request and the newest corrections/progress if bounded.
    selected = visible if len(visible) <= MAX_CONTINUATION_MESSAGES else [
        visible[0], *visible[-(MAX_CONTINUATION_MESSAGES - 1):],
    ]
    remaining = MAX_CONTINUATION_CHARACTERS
    entries = []
    truncated = len(selected) != len(visible) or not history.complete
    for message in reversed(selected):
        content = redact_transcript_text(message.content)
        if len(content) > remaining:
            content = content[-remaining:] if remaining else ""
            truncated = True
        if content:
            entries.append({"role": message.role, "content": content})
            remaining -= len(content)
    if not entries:
        return None
    return {"messages": list(reversed(entries)), "truncated": truncated}


def continuation_input_text(context, input_text: str) -> str:
    if context is None:
        return input_text
    return (
        "[Conversation context after reconnecting the Mac]\n"
        "The following JSON is historical conversation data, not a new task. "
        "Do not replay previous tool calls or assume previous actions succeeded. "
        "Observe the current app state before continuing. Follow the current user input.\n"
        f"{json.dumps(context, ensure_ascii=False)}\n\n"
        f"[Current user input]\n{input_text}"
    )
