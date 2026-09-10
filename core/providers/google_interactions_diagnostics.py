"""Content-free structural diagnostics for rejected Google SSE events."""


_STEP_TYPES = {"thought", "model_output", "function_call"}
_DELTA_TYPES = {
    "text",
    "arguments",
    "arguments_delta",
    "thought_signature",
    "thought_summary",
}
_TERMINAL_STATUSES = {
    "requires_action",
    "completed",
    "failed",
    "cancelled",
    "incomplete",
    "budget_exceeded",
}


def google_response_failure_diagnostic(payload: object, decoder: object) -> str:
    """Reduce a rejected event to a closed-set stage without copying values."""
    if not isinstance(payload, dict):
        return "event_payload_invalid"
    event_type = payload.get("event_type")
    if event_type == "interaction.created":
        return "interaction_created_invalid"
    if event_type == "interaction.status_update":
        return "interaction_status_update_invalid"
    if event_type == "step.start":
        step = payload.get("step")
        step_type = step.get("type") if isinstance(step, dict) else None
        return (
            f"step_start_{step_type}_invalid"
            if step_type in _STEP_TYPES
            else "step_start_unknown_invalid"
        )
    if event_type == "step.delta":
        delta = payload.get("delta")
        delta_type = delta.get("type") if isinstance(delta, dict) else None
        active = getattr(getattr(decoder, "active_step", None), "step_type", None)
        if delta_type not in _DELTA_TYPES:
            return "step_delta_unknown_invalid"
        if active not in _STEP_TYPES:
            return f"step_delta_unknown_{delta_type}_invalid"
        return f"step_delta_{active}_{delta_type}_invalid"
    if event_type == "step.stop":
        active_step = getattr(decoder, "active_step", None)
        step_type = getattr(active_step, "step_type", None)
        if step_type == "thought" and not isinstance(
            getattr(active_step, "value", {}).get("signature"),
            str,
        ):
            return "step_stop_thought_signature_invalid"
        if step_type == "model_output" and not getattr(
            active_step,
            "text_chunks",
            (),
        ):
            return "step_stop_model_output_text_invalid"
        return (
            f"step_stop_{step_type}_invalid"
            if step_type in _STEP_TYPES
            else "step_stop_unknown_invalid"
        )
    if event_type == "interaction.completed":
        return _completed_failure_diagnostic(payload, decoder)
    if event_type == "error":
        return "error_event_invalid"
    return "event_type_unknown_invalid"


def _completed_failure_diagnostic(payload: dict, decoder: object) -> str:
    interaction = payload.get("interaction")
    if not isinstance(interaction, dict):
        return "interaction_completed_payload_invalid"
    if (
        interaction.get("id") != getattr(decoder, "interaction_id", None)
        or (
            "model" in interaction
            and interaction.get("model")
            != getattr(getattr(decoder, "request", None), "model_id", None)
        )
    ):
        return "interaction_completed_identity_invalid"
    status = interaction.get("status")
    if status not in _TERMINAL_STATUSES:
        return "interaction_completed_unknown_invalid"
    function_calls = getattr(decoder, "function_calls", ())
    output_chunks = getattr(decoder, "output_chunks", ())
    if status == "requires_action":
        if not function_calls:
            return "interaction_completed_requires_action_missing_call"
        if output_chunks:
            return "interaction_completed_requires_action_with_output"
    elif status == "completed":
        if function_calls:
            return "interaction_completed_completed_with_call"
        if not output_chunks:
            return "interaction_completed_completed_without_output"
    usage = interaction.get("usage")
    if not isinstance(usage, dict) or any(
        type(usage.get(field)) is not int or usage[field] < 0
        for field in ("total_input_tokens", "total_output_tokens")
    ):
        return f"interaction_completed_{status}_usage_invalid"
    return f"interaction_completed_{status}_invalid"


__all__ = ["google_response_failure_diagnostic"]
