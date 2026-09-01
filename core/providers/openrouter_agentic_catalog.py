"""Fail-closed OpenRouter endpoint-catalog preflight for the pinned profile."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import socket
from dataclasses import dataclass
from urllib import error as urllib_error
from urllib import request as urllib_request

from core.providers.agentic_protocol import AgenticModelRequest, EphemeralCredential
from core.providers.openrouter_agentic_models import (
    OPENROUTER_AGENTIC_MODEL_ID,
    OPENROUTER_AGENTIC_MODEL_REVISION,
    OPENROUTER_AGENTIC_UPSTREAM_ID,
    OpenRouterAgenticProtocolError,
)
from core.providers.openrouter_agentic_request import openrouter_chat_payload
from core.providers.openrouter_agentic_state import decode_openrouter_chat_state
from core.runtime.execution_binding import canonical_digest
from core.runtime.hosted_agentic_budget import estimate_hosted_request_tokens


OPENROUTER_AGENTIC_ENDPOINT_CATALOG = (
    "https://openrouter.ai/api/v1/models/deepseek/deepseek-v4-flash/endpoints"
)
OPENROUTER_ZDR_ENDPOINT_CATALOG = "https://openrouter.ai/api/v1/endpoints/zdr"
MAX_OPENROUTER_CATALOG_BYTES = 8 * 1_048_576
OPENROUTER_CATALOG_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class OpenRouterAgenticCatalogSnapshot:
    """Redaction-safe identity of the two records accepted by preflight."""

    upstream_id: str
    supported_parameters: tuple[str, ...]
    model_catalog_record_digest: str
    zdr_catalog_record_digest: str
    supports_tool_choice_none: bool
    context_length: int
    max_completion_tokens: int
    catalog_snapshot_digest: str


def preflight_openrouter_agentic_catalog(
    request: AgenticModelRequest,
    *,
    credential: EphemeralCredential,
) -> OpenRouterAgenticCatalogSnapshot:
    """Fetch both official catalogs and reject drift before a completion request."""
    # Both snapshots are part of one pre-dispatch decision. Fetch them in
    # parallel so two catalog timeouts cannot consume the protected terminal
    # request reserve before completion transport begins.
    with ThreadPoolExecutor(
        max_workers=2,
        thread_name_prefix="openrouter-catalog-preflight",
    ) as executor:
        model_future = executor.submit(
            _fetch_catalog,
            OPENROUTER_AGENTIC_ENDPOINT_CATALOG,
            credential,
        )
        zdr_future = executor.submit(
            _fetch_catalog,
            OPENROUTER_ZDR_ENDPOINT_CATALOG,
            credential,
        )
        model_catalog = model_future.result()
        zdr_catalog = zdr_future.result()
    return validate_openrouter_agentic_catalog(
        request,
        model_catalog=model_catalog,
        zdr_catalog=zdr_catalog,
    )


def validate_openrouter_agentic_catalog(
    request: AgenticModelRequest,
    *,
    model_catalog: object,
    zdr_catalog: object,
) -> OpenRouterAgenticCatalogSnapshot:
    """Require the exact active DeepInfra FP8 endpoint and every routed parameter."""
    if (
        request.model_id != OPENROUTER_AGENTIC_MODEL_ID
        or request.model_revision_policy != "provider_alias"
        or request.model_revision != OPENROUTER_AGENTIC_MODEL_REVISION
    ):
        raise OpenRouterAgenticProtocolError("provider_request_invalid")
    model_record = _find_model_record(model_catalog)
    zdr_record = _find_zdr_record(zdr_catalog)
    required = _required_supported_parameters(request)
    required_context_tokens = (
        estimate_hosted_request_tokens(request) + request.max_output_tokens
    )
    model_parameters = _validate_record(
        model_record,
        required=required,
        max_output_tokens=request.max_output_tokens,
        required_context_tokens=required_context_tokens,
    )
    zdr_parameters = _validate_record(
        zdr_record,
        required=required,
        max_output_tokens=request.max_output_tokens,
        required_context_tokens=required_context_tokens,
    )
    model_none = _supports_tool_choice_none(model_record)
    zdr_none = _supports_tool_choice_none(zdr_record)
    if not model_none or not zdr_none:
        raise OpenRouterAgenticProtocolError(
            "provider_endpoint_parameters_unsupported"
        )
    model_context = _positive_int(model_record.get("context_length"))
    zdr_context = _positive_int(zdr_record.get("context_length"))
    model_completion = _positive_int(model_record.get("max_completion_tokens"))
    zdr_completion = _positive_int(zdr_record.get("max_completion_tokens"))
    snapshot_payload = {
        "upstream_id": OPENROUTER_AGENTIC_UPSTREAM_ID,
        "supported_parameters": tuple(sorted(model_parameters & zdr_parameters)),
        "model_catalog_record_digest": canonical_digest(
            _catalog_identity(model_record)
        ),
        "zdr_catalog_record_digest": canonical_digest(
            _catalog_identity(zdr_record)
        ),
        "supports_tool_choice_none": True,
        "context_length": min(model_context, zdr_context),
        "max_completion_tokens": min(model_completion, zdr_completion),
    }
    return OpenRouterAgenticCatalogSnapshot(
        **snapshot_payload,
        catalog_snapshot_digest=canonical_digest(snapshot_payload),
    )


def _required_supported_parameters(request: AgenticModelRequest) -> frozenset[str]:
    state = decode_openrouter_chat_state(request.provider_private_state)
    payload, _new_messages = openrouter_chat_payload(request, state)
    # These fields belong to OpenRouter's transport/routing envelope rather
    # than an endpoint's advertised generation-parameter set.
    envelope_fields = {"model", "messages", "provider", "stream", "stream_options"}
    required = set(payload) - envelope_fields
    if "reasoning" in payload:
        required.add("reasoning_effort")
    return frozenset(required)


def _find_model_record(payload: object) -> dict[str, object]:
    root = _mapping(payload)
    data = _mapping(root.get("data"))
    if data.get("id") != OPENROUTER_AGENTIC_MODEL_ID:
        raise OpenRouterAgenticProtocolError("provider_endpoint_parameters_unsupported")
    return _one_matching_record(data.get("endpoints"), require_model=False)


def _find_zdr_record(payload: object) -> dict[str, object]:
    root = _mapping(payload)
    return _one_matching_record(root.get("data"), require_model=True)


def _one_matching_record(value: object, *, require_model: bool) -> dict[str, object]:
    if not isinstance(value, list):
        raise OpenRouterAgenticProtocolError("provider_endpoint_parameters_unsupported")
    matches = []
    for item in value:
        if not isinstance(item, dict) or item.get("tag") != OPENROUTER_AGENTIC_UPSTREAM_ID:
            continue
        if require_model and item.get("model_id") != OPENROUTER_AGENTIC_MODEL_ID:
            continue
        matches.append(dict(item))
    if len(matches) != 1:
        raise OpenRouterAgenticProtocolError("provider_endpoint_parameters_unsupported")
    return matches[0]


def _validate_record(
    record: dict[str, object],
    *,
    required: frozenset[str],
    max_output_tokens: int,
    required_context_tokens: int,
) -> frozenset[str]:
    parameters = record.get("supported_parameters")
    if not isinstance(parameters, list) or any(not isinstance(item, str) for item in parameters):
        raise OpenRouterAgenticProtocolError("provider_endpoint_parameters_unsupported")
    supported = frozenset(parameters)
    completion_limit = record.get("max_completion_tokens")
    status = record.get("status")
    if (
        record.get("provider_name") != "DeepInfra"
        or record.get("quantization") != "fp8"
        or not isinstance(status, int)
        or isinstance(status, bool)
        or status != 0
        or not required.issubset(supported)
        or not isinstance(completion_limit, int)
        or isinstance(completion_limit, bool)
        or completion_limit < max_output_tokens
        or _positive_int(record.get("context_length")) < required_context_tokens
    ):
        raise OpenRouterAgenticProtocolError("provider_endpoint_parameters_unsupported")
    return supported


def _catalog_identity(record: dict[str, object]) -> dict[str, object]:
    return {
        "model_id": record.get("model_id", OPENROUTER_AGENTIC_MODEL_ID),
        "provider_name": record.get("provider_name"),
        "tag": record.get("tag"),
        "quantization": record.get("quantization"),
        "context_length": record.get("context_length"),
        "max_completion_tokens": record.get("max_completion_tokens"),
        "supported_parameters": tuple(sorted(record.get("supported_parameters", ()))),
        "supports_tool_choice": record.get("supports_tool_choice"),
        "status": record.get("status"),
    }


def _supports_tool_choice_none(record: dict[str, object]) -> bool:
    value = record.get("supports_tool_choice")
    return (
        isinstance(value, dict)
        and value.get("none") is True
        and value.get("auto") is True
        and all(isinstance(item, bool) for item in value.values())
    )


def _positive_int(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise OpenRouterAgenticProtocolError(
            "provider_endpoint_parameters_unsupported"
        )
    return value


def _fetch_catalog(url: str, credential: EphemeralCredential) -> object:
    request = urllib_request.Request(
        url,
        method="GET",
        headers={
            "Authorization": f"Bearer {credential.reveal()}",
            "Accept": "application/json",
            "User-Agent": "Maverick-Agentic-Certification/1",
        },
    )
    opener = urllib_request.build_opener(_RejectRedirects())
    response = None
    try:
        response = opener.open(
            request,
            timeout=OPENROUTER_CATALOG_TIMEOUT_SECONDS,
        )
        if response.geturl() != url:
            raise OpenRouterAgenticProtocolError("provider_request_rejected")
        payload = response.read(MAX_OPENROUTER_CATALOG_BYTES + 1)
        if len(payload) > MAX_OPENROUTER_CATALOG_BYTES:
            raise OpenRouterAgenticProtocolError("provider_response_invalid")
        return json.loads(payload)
    except OpenRouterAgenticProtocolError:
        raise
    except urllib_error.HTTPError as error:
        reason = "provider_authentication_failed" if error.code in {401, 403} else "provider_unavailable"
        raise OpenRouterAgenticProtocolError(reason) from error
    except (TimeoutError, socket.timeout, urllib_error.URLError, OSError, ValueError) as error:
        raise OpenRouterAgenticProtocolError("provider_unavailable") from error
    finally:
        if response is not None:
            response.close()


class _RejectRedirects(urllib_request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise OpenRouterAgenticProtocolError("provider_request_rejected")


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise OpenRouterAgenticProtocolError("provider_endpoint_parameters_unsupported")
    return dict(value)


__all__ = [
    "OpenRouterAgenticCatalogSnapshot",
    "preflight_openrouter_agentic_catalog",
    "validate_openrouter_agentic_catalog",
]
