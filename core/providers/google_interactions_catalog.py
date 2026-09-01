"""Live Google Interactions endpoint/model preflight for the pinned recipe."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
import socket
from urllib import error as urllib_error
from urllib import request as urllib_request

from core.providers.agentic_protocol import AgenticModelRequest, EphemeralCredential
from core.providers.google_interactions_client import (
    GOOGLE_AGENTIC_MODEL_ID,
    GOOGLE_AGENTIC_MODEL_REVISION,
)
from core.providers.google_interactions_models import GoogleInteractionsProtocolError
from core.providers.google_interactions_request import google_interaction_payload
from core.providers.google_interactions_state import decode_google_interaction_state
from core.runtime.execution_binding import canonical_digest
from core.runtime.hosted_agentic_budget import estimate_hosted_request_tokens


GOOGLE_INTERACTIONS_OPENAPI_CATALOG = (
    "https://ai.google.dev/static/api/interactions-v1.openapi.json"
)
GOOGLE_INTERACTIONS_MODEL_CATALOG = (
    "https://generativelanguage.googleapis.com/v1/models/gemini-3.6-flash"
)
GOOGLE_INTERACTIONS_CATALOG_TIMEOUT_SECONDS = 5.0
MAX_GOOGLE_INTERACTIONS_CATALOG_BYTES = 8 * 1_048_576


@dataclass(frozen=True)
class GoogleInteractionsCatalogSnapshot:
    """Redaction-safe identity of the live endpoint schema and model record."""

    api_version: str
    operation_id: str
    model_name: str
    model_version: str
    input_token_limit: int
    output_token_limit: int
    streaming: bool
    usage_accounting: bool
    tool_calling: bool
    endpoint_schema_digest: str
    model_record_digest: str
    catalog_snapshot_digest: str


def preflight_google_interactions_catalog(
    request: AgenticModelRequest,
    *,
    credential: EphemeralCredential,
) -> GoogleInteractionsCatalogSnapshot:
    """Fetch Google's live published schema and exact model before transport."""
    with ThreadPoolExecutor(
        max_workers=2,
        thread_name_prefix="google-interactions-preflight",
    ) as executor:
        schema_future = executor.submit(
            _fetch_catalog,
            GOOGLE_INTERACTIONS_OPENAPI_CATALOG,
            None,
        )
        model_future = executor.submit(
            _fetch_catalog,
            GOOGLE_INTERACTIONS_MODEL_CATALOG,
            credential,
        )
        endpoint_schema = schema_future.result()
        model_record = model_future.result()
    return validate_google_interactions_catalog(
        request,
        endpoint_schema=endpoint_schema,
        model_record=model_record,
    )


def validate_google_interactions_catalog(
    request: AgenticModelRequest,
    *,
    endpoint_schema: object,
    model_record: object,
) -> GoogleInteractionsCatalogSnapshot:
    """Validate exact request controls against both live authoritative records."""
    if request.model_id != GOOGLE_AGENTIC_MODEL_ID:
        raise GoogleInteractionsProtocolError("provider_request_invalid")
    root = _mapping(endpoint_schema)
    info = _mapping(root.get("info"))
    servers = root.get("servers")
    paths = _mapping(root.get("paths"))
    operation = _mapping(
        _mapping(paths.get("/{api_version}/interactions")).get("post")
    )
    components = _mapping(root.get("components"))
    schemas = _mapping(components.get("schemas"))
    request_schema = _mapping(schemas.get("CreateModelInteractionParams"))
    request_properties = _mapping(request_schema.get("properties"))
    generation_schema = _mapping(schemas.get("GenerationConfig"))
    generation_properties = _mapping(generation_schema.get("properties"))
    model_option = _mapping(schemas.get("ModelOption"))
    tool_schema = _mapping(schemas.get("Tool"))
    function_schema = _mapping(schemas.get("Function"))
    function_properties = _mapping(function_schema.get("properties"))
    usage_schema = _mapping(schemas.get("Usage"))
    usage_properties = _mapping(usage_schema.get("properties"))
    state = decode_google_interaction_state(
        request.provider_private_state,
        default_mode="stateless",
    )
    payload, _new_input = google_interaction_payload(request, state)
    generation_config = _mapping(payload.get("generation_config"))
    responses = _mapping(operation.get("responses"))
    success_content = _mapping(_mapping(responses.get("200")).get("content"))
    request_body = _mapping(operation.get("requestBody"))
    request_body_content = _mapping(request_body.get("content"))
    request_body_schema = _mapping(
        _mapping(request_body_content.get("application/json")).get("schema")
    )
    request_body_alternatives = request_body_schema.get("oneOf")
    model_values = model_option.get("enum")
    required_request_capabilities = {
        "generation_config",
        "input",
        "model",
        "store",
        "stream",
        "system_instruction",
        "tools",
        "usage",
    }
    tool_alternatives = tool_schema.get("oneOf")
    tool_refs = (
        {
            str(_mapping(item).get("$ref") or "")
            for item in tool_alternatives
        }
        if isinstance(tool_alternatives, list)
        else set()
    )
    request_body_refs = (
        {
            str(_mapping(item).get("$ref") or "")
            for item in request_body_alternatives
        }
        if isinstance(request_body_alternatives, list)
        else set()
    )
    if (
        root.get("openapi") != "3.0.3"
        or info.get("version") != "v1"
        or not isinstance(servers, list)
        or len(servers) != 1
        or _mapping(servers[0]).get("url")
        != "https://generativelanguage.googleapis.com"
        or operation.get("operationId") != "CreateInteraction"
        or request_body.get("required") is not True
        or "#/components/schemas/CreateModelInteractionParams"
        not in request_body_refs
        or set(request_schema.get("required", ())) != {"input", "model"}
        or not required_request_capabilities.issubset(request_properties)
        or not set(payload).issubset(request_properties)
        or not set(generation_config).issubset(generation_properties)
        or not {"max_output_tokens", "thinking_level", "thinking_summaries"}.issubset(
            generation_properties
        )
        or "text/event-stream" not in success_content
        or "#/components/schemas/Function" not in tool_refs
        or not {"name", "description", "parameters", "type"}.issubset(
            function_properties
        )
        or not {"total_input_tokens", "total_output_tokens", "total_tokens"}.issubset(
            usage_properties
        )
        or not isinstance(model_values, list)
        or request.model_id not in model_values
        and f"models/{request.model_id}" not in model_values
    ):
        raise GoogleInteractionsProtocolError(
            "provider_endpoint_parameters_unsupported"
        )
    record = _mapping(model_record)
    input_limit = _positive_int(record.get("inputTokenLimit"))
    output_limit = _positive_int(record.get("outputTokenLimit"))
    model_name = str(record.get("name") or "")
    model_version = str(record.get("version") or "")
    supported_methods = record.get("supportedGenerationMethods")
    required_input = estimate_hosted_request_tokens(request)
    if (
        model_name != f"models/{request.model_id}"
        or str(record.get("baseModelId") or "") != request.model_id
        or request.model_revision_policy != "exact"
        or request.model_revision != GOOGLE_AGENTIC_MODEL_REVISION
        or model_version != request.model_revision
        or not isinstance(supported_methods, list)
        or not supported_methods
        or any(not isinstance(item, str) for item in supported_methods)
        or input_limit < required_input
        or output_limit < request.max_output_tokens
        or request.reasoning_effort is not None
        and record.get("thinking") is not True
    ):
        raise GoogleInteractionsProtocolError(
            "provider_endpoint_parameters_unsupported"
        )
    endpoint_identity = {
        "openapi": root.get("openapi"),
        "info": {
            "version": info.get("version"),
            "x-google-revision": info.get("x-google-revision"),
        },
        "servers": servers,
        "operation": operation,
        "request_schema": request_schema,
        "generation_config": generation_schema,
        "model_option": model_option,
        "tool": tool_schema,
        "function": function_schema,
        "usage": usage_schema,
    }
    model_identity = {
        "name": model_name,
        "baseModelId": record.get("baseModelId"),
        "version": model_version,
        "inputTokenLimit": input_limit,
        "outputTokenLimit": output_limit,
        "supportedGenerationMethods": tuple(sorted(supported_methods)),
        "thinking": record.get("thinking"),
    }
    projection = {
        "api_version": "v1",
        "operation_id": "CreateInteraction",
        "model_name": model_name,
        "model_version": model_version,
        "input_token_limit": input_limit,
        "output_token_limit": output_limit,
        "streaming": True,
        "usage_accounting": True,
        "tool_calling": True,
        "endpoint_schema_digest": canonical_digest(endpoint_identity),
        "model_record_digest": canonical_digest(model_identity),
    }
    return GoogleInteractionsCatalogSnapshot(
        **projection,
        catalog_snapshot_digest=canonical_digest(projection),
    )


def _fetch_catalog(
    url: str,
    credential: EphemeralCredential | None,
) -> object:
    headers = {
        "Accept": "application/json",
        "User-Agent": "Maverick-Agentic-Certification/1",
    }
    if credential is not None:
        headers["x-goog-api-key"] = credential.reveal()
    request = urllib_request.Request(url, method="GET", headers=headers)
    opener = urllib_request.build_opener(_RejectRedirects())
    response = None
    try:
        response = opener.open(
            request,
            timeout=GOOGLE_INTERACTIONS_CATALOG_TIMEOUT_SECONDS,
        )
        if response.geturl() != url:
            raise GoogleInteractionsProtocolError("provider_request_rejected")
        payload = response.read(MAX_GOOGLE_INTERACTIONS_CATALOG_BYTES + 1)
        if len(payload) > MAX_GOOGLE_INTERACTIONS_CATALOG_BYTES:
            raise GoogleInteractionsProtocolError("provider_response_invalid")
        return json.loads(payload)
    except GoogleInteractionsProtocolError:
        raise
    except urllib_error.HTTPError as error:
        reason = (
            "provider_authentication_failed"
            if credential is not None and error.code in {400, 401, 403}
            else "provider_unavailable"
        )
        raise GoogleInteractionsProtocolError(reason) from error
    except (
        TimeoutError,
        socket.timeout,
        urllib_error.URLError,
        OSError,
        ValueError,
    ) as error:
        raise GoogleInteractionsProtocolError("provider_unavailable") from error
    finally:
        if response is not None:
            response.close()


class _RejectRedirects(urllib_request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise GoogleInteractionsProtocolError("provider_request_rejected")


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise GoogleInteractionsProtocolError(
            "provider_endpoint_parameters_unsupported"
        )
    return dict(value)


def _positive_int(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise GoogleInteractionsProtocolError(
            "provider_endpoint_parameters_unsupported"
        )
    return value


__all__ = [
    "GoogleInteractionsCatalogSnapshot",
    "preflight_google_interactions_catalog",
    "validate_google_interactions_catalog",
]
