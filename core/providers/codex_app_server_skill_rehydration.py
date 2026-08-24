"""Restore explicitly invoked Codex skills after in-turn context compaction."""

from __future__ import annotations

import threading
import time

from core.providers.codex_app_server_runtime_errors import (
    CodexAppServerDeliveryUncertainError,
    CodexAppServerRequestError,
)
from core.providers.codex_app_server_runtime_state import _CodexAppServerRuntime
from core.providers.codex_app_server_runtime_transport import _send_request
from core.providers.codex_skill_inputs import codex_skill_input_items
from core.runtime.execution_events import RuntimeExecutionEvent
from core.skills.models import SkillDefinition


SKILL_REHYDRATION_INPUT_TEXT = (
    "Restore the explicitly invoked skill instructions after context compaction, "
    "then continue the current task without changing its objective."
)
_REHYDRATION_RETRY_DELAYS = (0.05, 0.1, 0.2)


def schedule_codex_skill_rehydration(
    runtime: _CodexAppServerRuntime,
    *,
    compaction_item_id: str,
) -> bool:
    """Schedule one non-reader-thread steer for a completed compaction item."""
    with runtime.active_turn_lock:
        provider_thread_id = str(runtime.provider_thread_id or "").strip()
        provider_turn_id = str(runtime.current_provider_turn_id or "").strip()
    with runtime.skill_rehydration_lock:
        invoked_skills = tuple(runtime.current_invoked_skills)
        normalized_item_id = str(compaction_item_id or "").strip()
        if not normalized_item_id:
            runtime.skill_rehydration_sequence += 1
            normalized_item_id = f"anonymous:{runtime.skill_rehydration_sequence}"
        dedupe_key = f"{provider_turn_id}:{normalized_item_id}"
        if (
            not provider_thread_id
            or not provider_turn_id
            or not invoked_skills
            or dedupe_key in runtime.rehydrated_compaction_items
        ):
            return False
        runtime.rehydrated_compaction_items.add(dedupe_key)

    worker = threading.Thread(
        target=_rehydrate_codex_skills_after_compaction,
        kwargs={
            "runtime": runtime,
            "expected_provider_thread_id": provider_thread_id,
            "expected_provider_turn_id": provider_turn_id,
            "invoked_skills": invoked_skills,
        },
        daemon=True,
        name=f"codex-skill-rehydrate-{runtime.session_id}",
    )
    worker.start()
    return True


def _rehydrate_codex_skills_after_compaction(
    runtime: _CodexAppServerRuntime,
    *,
    expected_provider_thread_id: str,
    expected_provider_turn_id: str,
    invoked_skills: tuple[SkillDefinition, ...],
) -> bool:
    """Steer validated skill items into the still-active turn after compaction."""
    with runtime.steering_lock:
        with runtime.active_turn_lock:
            if (
                runtime.process.poll() is not None
                or runtime.provider_thread_id != expected_provider_thread_id
                or runtime.current_provider_turn_id != expected_provider_turn_id
            ):
                return False
        with runtime.skill_rehydration_lock:
            current_invoked_skills = tuple(runtime.current_invoked_skills)
            if not current_invoked_skills:
                return False
            invoked_skills = current_invoked_skills
        input_items = [
            {"type": "text", "text": SKILL_REHYDRATION_INPUT_TEXT},
            *codex_skill_input_items(runtime.runtime_root, list(invoked_skills)),
        ]
        for attempt in range(len(_REHYDRATION_RETRY_DELAYS) + 1):
            try:
                _send_request(
                    runtime,
                    "turn/steer",
                    {
                        "threadId": expected_provider_thread_id,
                        "expectedTurnId": expected_provider_turn_id,
                        "input": input_items,
                    },
                    timeout=5.0,
                )
            except CodexAppServerDeliveryUncertainError:
                _emit_rehydration_event(
                    runtime,
                    succeeded=False,
                    invoked_skills=invoked_skills,
                    failure_reason="delivery_uncertain",
                )
                return False
            except CodexAppServerRequestError as error:
                if attempt < len(_REHYDRATION_RETRY_DELAYS) and _retryable_rehydration_rejection(error):
                    time.sleep(_REHYDRATION_RETRY_DELAYS[attempt])
                    continue
                _emit_rehydration_event(
                    runtime,
                    succeeded=False,
                    invoked_skills=invoked_skills,
                    failure_reason="provider_rejected",
                )
                return False
            except Exception:
                _emit_rehydration_event(
                    runtime,
                    succeeded=False,
                    invoked_skills=invoked_skills,
                    failure_reason="provider_input_invalid",
                )
                return False
            _emit_rehydration_event(runtime, succeeded=True, invoked_skills=invoked_skills)
            return True
    return False


def _retryable_rehydration_rejection(error: CodexAppServerRequestError) -> bool:
    if error.code == -32001:
        return True
    message = error.message.lower()
    return any(token in message for token in ("compact", "not steerable", "backpressure", "overloaded"))


def _emit_rehydration_event(
    runtime: _CodexAppServerRuntime,
    *,
    succeeded: bool,
    invoked_skills: tuple[SkillDefinition, ...],
    failure_reason: str = "",
) -> None:
    with runtime.event_lock:
        sink = runtime.current_event_sink
    if sink is None:
        return
    payload: dict[str, object] = {
        "provider_id": "codex",
        "skill_ids": [skill.skill_id for skill in invoked_skills],
        "reason": "context_compaction",
    }
    if failure_reason:
        payload["failure_reason"] = failure_reason
    sink(
        RuntimeExecutionEvent(
            event_type=(
                "runtime.skill.rehydrated"
                if succeeded
                else "runtime.skill.rehydration_failed"
            ),
            payload=payload,
        )
    )


__all__ = ["schedule_codex_skill_rehydration"]
