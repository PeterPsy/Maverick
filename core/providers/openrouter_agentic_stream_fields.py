"""Strict field parsing for OpenRouter agentic response chunks."""

from __future__ import annotations

import json

from core.providers.openrouter_agentic_models import OpenRouterAgenticProtocolError


def object_field(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise OpenRouterAgenticProtocolError("provider_response_invalid")
    return value


def required_text(value: object, *, max_length: int = 16_384) -> str:
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise OpenRouterAgenticProtocolError("provider_response_invalid")
    return value


def nonnegative_int(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise OpenRouterAgenticProtocolError("provider_response_invalid")
    return value


def parsed_arguments(value: str) -> dict[str, object]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as cause:
        raise OpenRouterAgenticProtocolError("provider_response_invalid") from cause
    if not isinstance(parsed, dict):
        raise OpenRouterAgenticProtocolError("provider_response_invalid")
    return parsed


def validate_router_metadata(
    payload: object,
    *,
    model_id: str,
    top_level_provider: str,
    upstream_provider_names: tuple[str, ...],
    resolved_model_ids: tuple[str, ...],
) -> None:
    metadata = object_field(payload)
    if metadata.get("requested") != model_id or metadata.get("attempt") != 1:
        raise OpenRouterAgenticProtocolError("provider_upstream_not_certified")
    endpoints = object_field(metadata.get("endpoints"))
    available = endpoints.get("available")
    if not isinstance(available, list):
        raise OpenRouterAgenticProtocolError("provider_upstream_not_certified")
    selected = [item for item in available if isinstance(item, dict) and item.get("selected") is True]
    if len(selected) != 1:
        raise OpenRouterAgenticProtocolError("provider_upstream_not_certified")
    selected_provider = required_text(selected[0].get("provider"))
    selected_model = required_text(selected[0].get("model"))
    allowed_models = {model_id, *resolved_model_ids}
    if (
        selected_provider != top_level_provider
        or (
            upstream_provider_names
            and selected_provider not in upstream_provider_names
        )
        or selected_model not in allowed_models
    ):
        raise OpenRouterAgenticProtocolError("provider_upstream_not_certified")
    attempts = metadata.get("attempts")
    if attempts is not None:
        if not isinstance(attempts, list) or len(attempts) != 1:
            raise OpenRouterAgenticProtocolError("provider_upstream_not_certified")
        attempt = object_field(attempts[0])
        if (
            attempt.get("provider") != selected_provider
            or attempt.get("model") != selected_model
            or attempt.get("status") != 200
        ):
            raise OpenRouterAgenticProtocolError("provider_upstream_not_certified")


def reasoning_details(value: object) -> list[dict[str, object]]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise OpenRouterAgenticProtocolError("provider_response_invalid")
    return [dict(item) for item in value]
