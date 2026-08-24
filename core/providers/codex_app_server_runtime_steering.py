"""Same-turn input for the persistent Codex app-server runtime."""

from __future__ import annotations

import random
import time

from core.providers.codex_app_server_runtime_errors import (
    CodexAppServerDeliveryUncertainError,
    CodexAppServerRequestError,
)
from core.providers.codex_app_server_runtime_state import _RUNTIMES, _RUNTIMES_LOCK
from core.providers.codex_app_server_runtime_transport import _send_request
from core.providers.models import RuntimeSteerResult
from core.providers.codex_skill_inputs import codex_provider_input_text, codex_skill_input_items
from core.skills.models import SkillDefinition


_STEER_BACKPRESSURE_RETRY_DELAYS = (0.05, 0.1, 0.2)


def steer_codex_app_server_turn(
    session_id: str,
    *,
    input_text: str,
    client_message_id: str | None = None,
    expected_provider_turn_id: str | None = None,
    invoked_skills: list[SkillDefinition] | None = None,
    skill_activation_mode: str = "implicit",
) -> RuntimeSteerResult:
    """Admit one user message into the live regular Codex turn."""
    with _RUNTIMES_LOCK:
        runtime = _RUNTIMES.get(session_id)
    if runtime is None or runtime.process.poll() is not None:
        return RuntimeSteerResult(status="not_active", reason="runtime_unavailable")

    with runtime.steering_lock:
        with runtime.active_turn_lock:
            provider_thread_id = runtime.provider_thread_id
            expected_turn_id = runtime.current_provider_turn_id
        if not provider_thread_id or not expected_turn_id:
            return RuntimeSteerResult(status="not_active", reason="provider_turn_unavailable")
        normalized_expected_turn_id = str(expected_provider_turn_id or "").strip()
        if normalized_expected_turn_id and expected_turn_id != normalized_expected_turn_id:
            return RuntimeSteerResult(
                status="not_active",
                provider_turn_id=expected_turn_id,
                reason="provider_turn_changed",
            )

        backpressure_retries = 0
        while True:
            params: dict[str, object] = {
                "threadId": provider_thread_id,
                "expectedTurnId": expected_turn_id,
                "input": [
                    {
                        "type": "text",
                        "text": codex_provider_input_text(
                            input_text,
                            skill_activation_mode=skill_activation_mode,
                        ),
                    },
                    *codex_skill_input_items(runtime.runtime_root, invoked_skills),
                ],
            }
            normalized_client_message_id = str(client_message_id or "").strip()
            if normalized_client_message_id:
                params["clientUserMessageId"] = normalized_client_message_id
            try:
                result = _send_request(runtime, "turn/steer", params, timeout=5.0)
            except CodexAppServerDeliveryUncertainError as error:
                return RuntimeSteerResult(
                    status="delivery_uncertain",
                    provider_turn_id=expected_turn_id,
                    reason=str(error),
                )
            except CodexAppServerRequestError as error:
                actual_turn_id = _actual_provider_turn_id(error.data)
                if actual_turn_id and actual_turn_id != expected_turn_id:
                    return RuntimeSteerResult(
                        status="not_active",
                        provider_turn_id=actual_turn_id,
                        reason="provider_turn_changed",
                    )
                normalized_message = error.message.lower()
                if error.code == -32001:
                    if backpressure_retries < len(_STEER_BACKPRESSURE_RETRY_DELAYS):
                        delay = _STEER_BACKPRESSURE_RETRY_DELAYS[backpressure_retries] * random.uniform(
                            0.8,
                            1.2,
                        )
                        backpressure_retries += 1
                        time.sleep(delay)
                        continue
                    return RuntimeSteerResult(
                        status="overloaded",
                        provider_turn_id=expected_turn_id,
                        reason="provider_backpressure",
                    )
                if "no active turn" in normalized_message or (
                    "active turn" in normalized_message and "not" in normalized_message
                ):
                    return RuntimeSteerResult(status="not_active", provider_turn_id=actual_turn_id, reason=error.message)
                if "expected active turn id" in normalized_message:
                    return RuntimeSteerResult(status="not_active", reason="provider_turn_changed")
                if _active_turn_not_steerable(error.data) or any(
                    token in normalized_message for token in ("not steerable", "review", "compact")
                ):
                    return RuntimeSteerResult(status="not_supported", provider_turn_id=actual_turn_id, reason=error.message)
                if "direct app-server input is not allowed" in normalized_message:
                    return RuntimeSteerResult(status="not_supported", reason=error.message)
                return RuntimeSteerResult(status="failed", provider_turn_id=actual_turn_id, reason=error.message)

            response_turn_id = str(result.get("turnId") or result.get("turn_id") or expected_turn_id).strip()
            if invoked_skills:
                with runtime.skill_rehydration_lock:
                    skills_by_id = {skill.skill_id: skill for skill in runtime.current_invoked_skills}
                    for skill in invoked_skills:
                        skills_by_id[skill.skill_id] = skill
                    runtime.current_invoked_skills = tuple(skills_by_id.values())
            return RuntimeSteerResult(status="steered", provider_turn_id=response_turn_id or expected_turn_id)


def _actual_provider_turn_id(data: object) -> str | None:
    if not isinstance(data, dict):
        return None
    for key in ("actualTurnId", "actual_turn_id", "turnId", "turn_id"):
        value = str(data.get(key) or "").strip()
        if value:
            return value
    return None


def _active_turn_not_steerable(data: object) -> bool:
    if not isinstance(data, dict):
        return False
    error_info = data.get("codexErrorInfo") or data.get("codex_error_info")
    return isinstance(error_info, dict) and bool(
        error_info.get("activeTurnNotSteerable") or error_info.get("active_turn_not_steerable")
    )
