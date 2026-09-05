"""Strict record selection and field checks for OpenRouter catalogs."""

from __future__ import annotations

from core.providers.agentic_protocol import AgenticModelRequest
from core.providers.openrouter_agentic_models import (
    OpenRouterAgenticProtocolError,
)


def configured_upstream_id(request: AgenticModelRequest) -> str:
    upstreams = tuple(request.routing_constraint.allowed_upstream_ids)
    if len(upstreams) != 1 or not str(upstreams[0] or "").strip():
        raise OpenRouterAgenticProtocolError("provider_request_invalid")
    return upstreams[0]


def find_model_record(
    payload: object,
    *,
    model_id: str,
    upstream_id: str,
) -> dict[str, object]:
    root = _mapping(payload)
    data = _mapping(root.get("data"))
    if data.get("id") != model_id:
        raise OpenRouterAgenticProtocolError(
            "provider_endpoint_parameters_unsupported"
        )
    return _one_matching_record(
        data.get("endpoints"),
        model_id=model_id,
        upstream_id=upstream_id,
        require_model=False,
    )


def find_zdr_record(
    payload: object,
    *,
    model_id: str,
    upstream_id: str,
) -> dict[str, object]:
    root = _mapping(payload)
    return _one_matching_record(
        root.get("data"),
        model_id=model_id,
        upstream_id=upstream_id,
        require_model=True,
    )


def validate_record(
    record: dict[str, object],
    *,
    required: frozenset[str],
    max_output_tokens: int,
    required_context_tokens: int,
    upstream_provider_names: tuple[str, ...],
    quantizations: frozenset[str],
) -> frozenset[str]:
    parameters = record.get("supported_parameters")
    if not isinstance(parameters, list) or any(
        not isinstance(item, str) for item in parameters
    ):
        raise OpenRouterAgenticProtocolError(
            "provider_endpoint_parameters_unsupported"
        )
    supported = frozenset(parameters)
    completion_limit = record.get("max_completion_tokens")
    status = record.get("status")
    if (
        not str(record.get("provider_name") or "").strip()
        or (
            upstream_provider_names
            and record.get("provider_name") not in upstream_provider_names
        )
        or record.get("quantization") not in quantizations
        or not isinstance(status, int)
        or isinstance(status, bool)
        or status != 0
        or not required.issubset(supported)
        or not isinstance(completion_limit, int)
        or isinstance(completion_limit, bool)
        or completion_limit < max_output_tokens
        or positive_int(record.get("context_length")) < required_context_tokens
    ):
        raise OpenRouterAgenticProtocolError(
            "provider_endpoint_parameters_unsupported"
        )
    return supported


def catalog_identity(
    record: dict[str, object],
    *,
    model_id: str,
) -> dict[str, object]:
    return {
        "model_id": record.get("model_id", model_id),
        "provider_name": record.get("provider_name"),
        "tag": record.get("tag"),
        "quantization": record.get("quantization"),
        "context_length": record.get("context_length"),
        "max_completion_tokens": record.get("max_completion_tokens"),
        "supported_parameters": tuple(
            sorted(record.get("supported_parameters", ()))
        ),
        "supports_tool_choice": record.get("supports_tool_choice"),
        "status": record.get("status"),
    }


def supports_tool_choice_none(record: dict[str, object]) -> bool:
    value = record.get("supports_tool_choice")
    return (
        isinstance(value, dict)
        and value.get("none") is True
        and value.get("auto") is True
        and all(isinstance(item, bool) for item in value.values())
    )


def positive_int(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise OpenRouterAgenticProtocolError(
            "provider_endpoint_parameters_unsupported"
        )
    return value


def _one_matching_record(
    value: object,
    *,
    model_id: str,
    upstream_id: str,
    require_model: bool,
) -> dict[str, object]:
    if not isinstance(value, list):
        raise OpenRouterAgenticProtocolError(
            "provider_endpoint_parameters_unsupported"
        )
    matches = []
    for item in value:
        if not isinstance(item, dict) or item.get("tag") != upstream_id:
            continue
        if require_model and item.get("model_id") != model_id:
            continue
        matches.append(dict(item))
    if len(matches) != 1:
        raise OpenRouterAgenticProtocolError(
            "provider_endpoint_parameters_unsupported"
        )
    return matches[0]


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise OpenRouterAgenticProtocolError(
            "provider_endpoint_parameters_unsupported"
        )
    return dict(value)


__all__ = [
    "catalog_identity",
    "configured_upstream_id",
    "find_model_record",
    "find_zdr_record",
    "positive_int",
    "supports_tool_choice_none",
    "validate_record",
]
