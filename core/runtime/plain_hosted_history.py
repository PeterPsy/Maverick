"""Conversation history builder for plain hosted chat turns."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from core.providers.text_generation import TextGenerationMessage


DEFAULT_MAX_HISTORY_TURNS = 20
DEFAULT_MAX_HISTORY_CHARS = 80_000
HISTORY_TURN_SCAN_MULTIPLIER = 4
HISTORY_EVENT_SCAN_MULTIPLIER = 50


@dataclass(frozen=True)
class _HistoryPair:
    turn_created_at: datetime
    turn_id: str
    user_text: str
    assistant_text: str


def build_plain_hosted_message_history(
    runtime_store,
    *,
    session_id: str,
    current_turn_id: str | None,
    current_input_text: str,
    max_history_turns: int = DEFAULT_MAX_HISTORY_TURNS,
    max_history_chars: int = DEFAULT_MAX_HISTORY_CHARS,
) -> list[TextGenerationMessage]:
    """Build hosted chat messages from completed prior runtime turns."""
    current_message = TextGenerationMessage(role="user", content=current_input_text)
    pairs = _completed_history_pairs(
        runtime_store,
        session_id=session_id,
        current_turn_id=current_turn_id,
        max_history_turns=max_history_turns,
    )
    messages = _messages_for_pairs(pairs) + [current_message]
    return _trim_complete_pairs(messages, max_history_chars=max_history_chars)


def _completed_history_pairs(
    runtime_store,
    *,
    session_id: str,
    current_turn_id: str | None,
    max_history_turns: int,
) -> list[_HistoryPair]:
    bounded_turns = max(0, int(max_history_turns))
    if not bounded_turns:
        return []
    turn_scan_limit = bounded_turns * HISTORY_TURN_SCAN_MULTIPLIER
    event_scan_limit = max(bounded_turns * HISTORY_EVENT_SCAN_MULTIPLIER, bounded_turns)
    completed_turns = [
        turn
        for turn in runtime_store.list_recent_turns(session_id, limit=turn_scan_limit)
        if turn.status == "completed" and turn.turn_id != current_turn_id and _non_empty_text(turn.input_text)
    ]
    completed_turns.sort(key=lambda turn: (turn.created_at, turn.turn_id))
    final_outputs = _latest_final_outputs_by_turn(runtime_store.list_recent_events(session_id, limit=event_scan_limit))
    pairs = [
        _HistoryPair(
            turn_created_at=turn.created_at,
            turn_id=turn.turn_id,
            user_text=str(turn.input_text or ""),
            assistant_text=final_outputs[turn.turn_id],
        )
        for turn in completed_turns
        if _non_empty_text(final_outputs.get(turn.turn_id))
    ]
    return pairs[-bounded_turns:]


def _latest_final_outputs_by_turn(events: list[Any]) -> dict[str, str]:
    candidates: dict[str, tuple[datetime, str, str]] = {}
    for event in events:
        if event.event_type != "runtime.output.final" or not event.turn_id:
            continue
        assistant_text = _final_event_complete_text(event.payload)
        if not _non_empty_text(assistant_text):
            continue
        candidate = (event.created_at, event.event_id, assistant_text)
        current = candidates.get(event.turn_id)
        if current is None or (candidate[0], candidate[1]) >= (current[0], current[1]):
            candidates[event.turn_id] = candidate
    return {turn_id: item[2] for turn_id, item in candidates.items()}


def _final_event_complete_text(payload: dict[str, Any]) -> str:
    complete_text = payload.get("complete_text")
    if isinstance(complete_text, str):
        return complete_text
    text = payload.get("text")
    return text if isinstance(text, str) else ""


def _messages_for_pairs(pairs: list[_HistoryPair]) -> list[TextGenerationMessage]:
    messages: list[TextGenerationMessage] = []
    for pair in pairs:
        messages.append(TextGenerationMessage(role="user", content=pair.user_text))
        messages.append(TextGenerationMessage(role="assistant", content=pair.assistant_text))
    return messages


def _trim_complete_pairs(messages: list[TextGenerationMessage], *, max_history_chars: int) -> list[TextGenerationMessage]:
    if not messages:
        return []
    current_message = messages[-1]
    history_messages = messages[:-1]
    budget = max(0, int(max_history_chars))
    if budget <= _message_text_length(current_message):
        return [current_message]
    selected_pairs: list[TextGenerationMessage] = []
    used_chars = _message_text_length(current_message)
    for index in range(len(history_messages) - 2, -1, -2):
        pair = history_messages[index : index + 2]
        if len(pair) != 2:
            continue
        pair_chars = sum(_message_text_length(message) for message in pair)
        if used_chars + pair_chars > budget:
            continue
        selected_pairs[0:0] = pair
        used_chars += pair_chars
    return selected_pairs + [current_message]


def _message_text_length(message: TextGenerationMessage) -> int:
    if isinstance(message.content, str):
        return len(message.content)
    return sum(len(part.text or "") for part in message.content if part.type == "text")


def _non_empty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())
