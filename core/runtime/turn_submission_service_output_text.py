"""Runtime turn output text recording helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from core.runtime.execution_events import RuntimeExecutionEvent
from core.runtime.output_compaction import ToolOutputCompactionContext, compact_tool_call_event
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.service import record_runtime_event

if TYPE_CHECKING:
    from core.api.platform_state import PlatformState


class _RuntimeTurnOutputRecorder:
    """Persist execution events and track text already emitted as streamed output."""

    def __init__(self, state: PlatformState, *, session_id: str, turn_id: str) -> None:
        self.state = state
        self.session_id = session_id
        self.turn_id = turn_id
        self._streamed_text_parts: list[str] = []

    def record(self, event: RuntimeExecutionEvent) -> RuntimeEventRecord:
        if event.event_type == "runtime.output.delta":
            text = event.payload.get("text")
            if isinstance(text, str) and text:
                self._streamed_text_parts.append(text)
        elif event.event_type.startswith("runtime.tool_call."):
            event = compact_tool_call_event(
                event,
                context=ToolOutputCompactionContext(
                    session_id=self.session_id,
                    turn_id=self.turn_id,
                ),
            )
        return _record_execution_event(self.state, session_id=self.session_id, turn_id=self.turn_id, event=event)

    def final_text(self, output_text: str) -> str:
        return _missing_final_suffix(output_text, "".join(self._streamed_text_parts))

    def complete_text(self, output_text: str) -> str:
        return _complete_output_text(output_text, "".join(self._streamed_text_parts))


def _missing_final_suffix(output_text: str, streamed_text: str) -> str:
    if not output_text or not streamed_text:
        return output_text
    if output_text.startswith(streamed_text):
        return output_text[len(streamed_text) :].lstrip()
    prefix_end = _prefix_end_ignoring_whitespace(output_text, streamed_text)
    if prefix_end is not None:
        return output_text[prefix_end:].lstrip()
    if _normalized_text(output_text) == _normalized_text(streamed_text):
        return ""
    return output_text


def _complete_output_text(output_text: str, streamed_text: str) -> str:
    if not streamed_text:
        return output_text
    if not output_text:
        return streamed_text
    if output_text.startswith(streamed_text):
        return output_text
    if _normalized_text(output_text) == _normalized_text(streamed_text):
        return streamed_text
    suffix = _missing_final_suffix(output_text, streamed_text)
    if suffix and suffix != output_text:
        separator = "" if streamed_text.endswith(("\n", " ")) else "\n"
        return f"{streamed_text}{separator}{suffix}"
    return output_text


def _prefix_end_ignoring_whitespace(text: str, prefix: str) -> int | None:
    text_index = 0
    prefix_index = 0
    while prefix_index < len(prefix):
        prefix_char = prefix[prefix_index]
        if prefix_char.isspace():
            while prefix_index < len(prefix) and prefix[prefix_index].isspace():
                prefix_index += 1
            if prefix_index >= len(prefix):
                while text_index < len(text) and text[text_index].isspace():
                    text_index += 1
                return text_index
            if text_index >= len(text) or not text[text_index].isspace():
                return None
            while text_index < len(text) and text[text_index].isspace():
                text_index += 1
            continue
        if text_index >= len(text) or text[text_index] != prefix_char:
            return None
        text_index += 1
        prefix_index += 1
    return text_index


def _normalized_text(value: str) -> str:
    return " ".join(value.split())


def _record_execution_event(
    state: PlatformState,
    *,
    session_id: str,
    turn_id: str,
    event: RuntimeExecutionEvent,
) -> RuntimeEventRecord:
    return record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn_id,
        plane="turn",
        event_type=event.event_type,
        payload=event.payload,
        event_bus=state.runtime_event_bus,
    )
