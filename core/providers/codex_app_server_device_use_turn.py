"""Device-specific turn input, authority, and start parameters."""

from __future__ import annotations

from core.device_use.contract import DEVICE_USE_REASONING_EFFORT
from core.device_use.errors import DeviceUseError
from core.device_use.runtime_registry import device_use_service_for_session
from core.providers.codex_skill_inputs import (
    codex_provider_input_text,
    codex_skill_input_items,
)
from core.runtime.research_runtime import runtime_session_is_research


def codex_turn_input(
    session,
    runtime,
    input_text: str,
    invoked_skills,
) -> tuple[bool, bool, list[dict[str, object]]]:
    """Keep Device Use prompts free of workspace skills and instruction wrappers."""
    device_use = getattr(session, "device_use_binding", None) is not None
    research = runtime_session_is_research(session)
    if research:
        return False, True, [{"type": "text", "text": input_text}]
    if device_use:
        return True, False, [{"type": "text", "text": input_text}]
    return False, False, [
        {
            "type": "text",
            "text": codex_provider_input_text(
                input_text,
                skill_activation_mode=getattr(session, "skill_activation_mode", "implicit"),
            ),
        },
        *codex_skill_input_items(
            runtime.runtime_root,
            invoked_skills,
            runtime_home=runtime.runtime_home,
        ),
    ]


def set_device_use_turn(runtime, *, runtime_turn_id: str | None, task_text: str) -> None:
    with runtime.active_turn_lock:
        runtime.current_runtime_turn_id = str(runtime_turn_id or "").strip() or None
        runtime.current_task_text = task_text if runtime.device_use_binding is not None else ""


def clear_device_use_turn(runtime) -> None:
    with runtime.active_turn_lock:
        runtime.current_runtime_turn_id = None
        runtime.current_task_text = ""


def finish_device_use_turn(runtime, runtime_turn_id: str | None) -> None:
    """Release the native task lease, then drop transient provider authority."""
    binding = runtime.device_use_binding
    service = device_use_service_for_session(runtime.session_id)
    try:
        if binding is not None and service is not None and runtime_turn_id:
            service.end_turn(
                binding,
                runtime_session_id=runtime.session_id,
                turn_id=runtime_turn_id,
            )
    except DeviceUseError:
        pass
    clear_device_use_turn(runtime)


def codex_turn_start_params(
    *,
    device_use: bool,
    research: bool,
    provider_thread_id: str,
    turn_input: list[dict[str, object]],
    launch_spec,
    sandbox_policy,
) -> dict[str, object]:
    params: dict[str, object] = {"threadId": provider_thread_id, "input": turn_input}
    if device_use:
        params["effort"] = DEVICE_USE_REASONING_EFFORT
    elif research:
        params.update({
            "approvalPolicy": "never",
            "sandboxPolicy": {"type": "readOnly"},
            "environments": [],
        })
    else:
        params.update({
            "approvalPolicy": "never",
            "sandboxPolicy": sandbox_policy(launch_spec),
            "cwd": launch_spec.working_directory,
        })
    return params
