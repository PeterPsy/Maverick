"""Canonical safe projection from runtime events to visible messages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.transcript_models import RuntimeTranscriptMessage, RuntimeTranscriptProjection
from core.runtime.transcript_safety import (
    safe_app_reference_items,
    safe_attachment_items,
    safe_structured_content,
)


@dataclass
class _OrderedMessage:
    order: tuple[datetime, int, str]
    sequence: int
    message: RuntimeTranscriptMessage


@dataclass
class _OutputSegment:
    text: str
    created_at: datetime
    order_event_id: str
    source_event_ids: list[str]
    index: int


def project_runtime_transcript(
    events: Iterable[RuntimeEventRecord],
    turns: Iterable[RuntimeTurnRecord],
) -> RuntimeTranscriptProjection:
    """Return only the conversation-visible projection of complete runtime history."""
    ordered_events = sorted(events, key=lambda item: (item.created_at, item.event_id))
    ordered_turns = sorted(turns, key=lambda item: (item.created_at, item.turn_id))
    turns_by_id = {turn.turn_id: turn for turn in ordered_turns}
    latest_final_by_turn = _latest_final_events(ordered_events)
    entries: list[_OrderedMessage] = []
    active_output: dict[str, _OutputSegment] = {}
    next_segment_index: dict[str, int] = {}
    rendered_output: dict[str, str] = {}
    seen_user_messages: set[str] = set()
    user_turn_ids: set[str] = set()
    terminal_turn_ids: set[str] = set()
    warnings: list[str] = []
    sequence = 0

    def push(
        message: RuntimeTranscriptMessage,
        *,
        order_event_id: str,
        order_rank: int = 1,
    ) -> _OrderedMessage:
        nonlocal sequence
        entry = _OrderedMessage(
            order=(message.created_at, order_rank, order_event_id),
            sequence=sequence,
            message=message,
        )
        entries.append(entry)
        sequence += 1
        return entry

    def flush_output(turn_id: str, *, complete: bool) -> None:
        segment = active_output.pop(turn_id, None)
        if segment is None or not segment.text:
            return
        turn = turns_by_id.get(turn_id)
        terminal = bool(turn and turn.status in {"completed", "failed", "cancelled", "timed-out"})
        push(
            RuntimeTranscriptMessage(
                message_id=f"{turn_id}:agent:stream:{segment.index}",
                turn_id=turn_id,
                role="agent",
                content=segment.text,
                status="complete" if complete or terminal else "pending",
                created_at=segment.created_at,
                source_event_ids=list(segment.source_event_ids),
            ),
            order_event_id=segment.order_event_id,
        )
        rendered_output[turn_id] = rendered_output.get(turn_id, "") + segment.text

    for event in ordered_events:
        turn_id = event.turn_id or event.event_id
        payload = event.payload if isinstance(event.payload, dict) else {}
        if event.event_type in {"runtime.turn.queued", "runtime.message.steered"}:
            if event.event_type == "runtime.message.steered":
                flush_output(turn_id, complete=True)
            input_text = payload.get("input_text") if isinstance(payload.get("input_text"), str) else ""
            attachments, attachment_redactions = safe_attachment_items(payload.get("attachments"))
            app_references, reference_redactions = safe_app_reference_items(payload.get("app_references"))
            client_message_id = str(payload.get("client_message_id") or "").strip()
            message_id = client_message_id or (
                f"{turn_id}:human" if event.event_type == "runtime.turn.queued" else f"{turn_id}:human:{event.event_id}"
            )
            if (input_text.strip() or attachments or app_references) and message_id not in seen_user_messages:
                push(
                    RuntimeTranscriptMessage(
                        message_id=message_id,
                        turn_id=event.turn_id,
                        role="human",
                        content=input_text,
                        status="complete",
                        created_at=event.created_at,
                        source_event_ids=[event.event_id],
                        attachments=attachments,
                        app_references=app_references,
                        redactions_applied=attachment_redactions or reference_redactions,
                    ),
                    order_event_id=event.event_id,
                )
                seen_user_messages.add(message_id)
                if event.turn_id:
                    user_turn_ids.add(event.turn_id)
            continue
        if event.event_type == "runtime.output.delta":
            text = payload.get("text") if isinstance(payload.get("text"), str) else ""
            if text:
                current = active_output.get(turn_id)
                if current is None:
                    index = next_segment_index.get(turn_id, 0)
                    next_segment_index[turn_id] = index + 1
                    active_output[turn_id] = _OutputSegment(
                        text=text,
                        created_at=event.created_at,
                        order_event_id=event.event_id,
                        source_event_ids=[event.event_id],
                        index=index,
                    )
                else:
                    current.text += text
                    current.source_event_ids.append(event.event_id)
            continue
        if event.event_type == "runtime.output.structured":
            flush_output(turn_id, complete=turn_id in latest_final_by_turn)
            structured, redacted, truncated = _structured_from_event(payload)
            if structured is not None:
                push(
                    RuntimeTranscriptMessage(
                        message_id=f"{turn_id}:structured:{event.event_id}",
                        turn_id=event.turn_id,
                        role="structured",
                        content=str(structured["kind"]),
                        status="complete",
                        created_at=event.created_at,
                        source_event_ids=[event.event_id],
                        structured_content=structured,
                        structured_content_truncated=truncated,
                        redactions_applied=redacted,
                    ),
                    order_event_id=event.event_id,
                )
            continue
        if event.event_type == "runtime.output.final":
            if latest_final_by_turn.get(turn_id) is not event:
                continue
            flush_output(turn_id, complete=True)
            _project_final_output(
                event,
                turn_id=turn_id,
                entries=entries,
                rendered_text=rendered_output.get(turn_id, ""),
                push=push,
            )
            continue
        if event.event_type in {"runtime.turn.failed", "runtime.turn.cancelled", "runtime.turn.timed-out"}:
            flush_output(turn_id, complete=True)
            terminal_turn_ids.add(turn_id)
            status, fallback = _terminal_status(event.event_type)
            content = _readable_status_text(payload, fallback=fallback)
            push(
                RuntimeTranscriptMessage(
                    message_id=f"{turn_id}:{status}",
                    turn_id=event.turn_id,
                    role="system",
                    content=content,
                    status=status,
                    created_at=event.created_at,
                    source_event_ids=[event.event_id],
                ),
                order_event_id=event.event_id,
            )

    for turn_id in list(active_output):
        flush_output(turn_id, complete=turn_id in latest_final_by_turn)

    for turn in ordered_turns:
        if turn.turn_id not in user_turn_ids and turn.input_text:
            message_id = turn.client_message_id or f"{turn.turn_id}:human"
            if message_id not in seen_user_messages:
                push(
                    RuntimeTranscriptMessage(
                        message_id=message_id,
                        turn_id=turn.turn_id,
                        role="human",
                        content=turn.input_text,
                        status="complete",
                        created_at=turn.created_at,
                    ),
                    order_event_id=f"turn:{turn.turn_id}",
                    order_rank=0,
                )
                seen_user_messages.add(message_id)
        if turn.turn_id in terminal_turn_ids or turn.status not in {"failed", "cancelled", "timed-out"}:
            continue
        status = turn.status
        content = turn.failure_reason or f"Runtime turn {status}."
        push(
            RuntimeTranscriptMessage(
                message_id=f"{turn.turn_id}:{status}",
                turn_id=turn.turn_id,
                role="system",
                content=content,
                status=status,
                created_at=turn.updated_at,
            ),
            order_event_id=f"turn-status:{turn.turn_id}",
        )

    entries.sort(key=lambda item: (item.order, item.sequence))
    message_ids: set[str] = set()
    messages: list[RuntimeTranscriptMessage] = []
    for entry in entries:
        if entry.message.message_id in message_ids:
            warnings.append(f"duplicate_message_id:{entry.message.message_id}")
            continue
        message_ids.add(entry.message.message_id)
        messages.append(entry.message)
    return RuntimeTranscriptProjection(messages=messages, warnings=warnings, complete=not warnings)


def _latest_final_events(events: list[RuntimeEventRecord]) -> dict[str, RuntimeEventRecord]:
    result: dict[str, RuntimeEventRecord] = {}
    for event in events:
        if event.event_type == "runtime.output.final":
            result[event.turn_id or event.event_id] = event
    return result


def _structured_from_event(payload: dict) -> tuple[dict | None, bool, bool]:
    for key in ("structured_content", "structuredContent", "content"):
        structured, redacted, truncated = safe_structured_content(payload.get(key))
        if structured is not None:
            return structured, redacted, truncated
    return None, False, False


def _project_final_output(event, *, turn_id: str, entries: list[_OrderedMessage], rendered_text: str, push) -> None:
    payload = event.payload if isinstance(event.payload, dict) else {}
    complete_text = payload.get("complete_text") if isinstance(payload.get("complete_text"), str) else ""
    final_text = payload.get("text") if isinstance(payload.get("text"), str) else ""
    has_complete_text = bool(complete_text.strip())
    has_final_text = bool(final_text.strip())
    authoritative = complete_text if has_complete_text else final_text if has_final_text else ""
    source_event_ids = [event.event_id]
    if has_complete_text and rendered_text:
        prefix_end = _prefix_end_ignoring_whitespace(complete_text, rendered_text)
        if prefix_end is None:
            removed = [
                entry for entry in entries
                if entry.message.turn_id == event.turn_id and entry.message.message_id.startswith(f"{turn_id}:agent:stream:")
            ]
            source_event_ids = [source for entry in removed for source in entry.message.source_event_ids] + source_event_ids
            entries[:] = [entry for entry in entries if entry not in removed]
        else:
            authoritative = complete_text[prefix_end:]
            if not authoritative:
                stream_entries = [
                    entry for entry in entries
                    if entry.message.turn_id == event.turn_id and entry.message.message_id.startswith(f"{turn_id}:agent:stream:")
                ]
                if stream_entries:
                    stream_entries[-1].message.source_event_ids.append(event.event_id)
    elif rendered_text and has_final_text:
        prefix_end = _prefix_end_ignoring_whitespace(final_text, rendered_text)
        authoritative = final_text[prefix_end:] if prefix_end is not None else final_text
    structured, structured_redacted, structured_truncated = _structured_from_event(payload)
    if structured is not None:
        push(
            RuntimeTranscriptMessage(
                message_id=f"{turn_id}:structured:{event.event_id}",
                turn_id=event.turn_id,
                role="structured",
                content=str(structured["kind"]),
                status="complete",
                created_at=event.created_at,
                source_event_ids=[event.event_id],
                structured_content=structured,
                structured_content_truncated=structured_truncated,
                redactions_applied=structured_redacted,
            ),
            order_event_id=event.event_id,
        )
    if authoritative:
        push(
            RuntimeTranscriptMessage(
                message_id=f"{turn_id}:agent",
                turn_id=event.turn_id,
                role="agent",
                content=authoritative,
                status="complete",
                created_at=event.created_at,
                source_event_ids=source_event_ids,
            ),
            order_event_id=event.event_id,
        )


def _prefix_end_ignoring_whitespace(text: str, prefix: str) -> int | None:
    if not prefix:
        return 0
    text_index = 0
    prefix_index = 0
    while prefix_index < len(prefix):
        if prefix[prefix_index].isspace():
            while prefix_index < len(prefix) and prefix[prefix_index].isspace():
                prefix_index += 1
            while text_index < len(text) and text[text_index].isspace():
                text_index += 1
            continue
        if text_index >= len(text) or text[text_index] != prefix[prefix_index]:
            return None
        text_index += 1
        prefix_index += 1
    return text_index


def _terminal_status(event_type: str) -> tuple[str, str]:
    if event_type == "runtime.turn.cancelled":
        return "cancelled", "Runtime turn cancelled."
    if event_type == "runtime.turn.timed-out":
        return "timed-out", "Runtime turn timed out."
    return "failed", "Runtime turn failed."


def _readable_status_text(payload: dict, *, fallback: str) -> str:
    for key in ("reason", "error", "failure_reason", "exit_code"):
        value = payload.get(key)
        if value not in (None, ""):
            return str(value).strip().replace("_", " ")
    return fallback
