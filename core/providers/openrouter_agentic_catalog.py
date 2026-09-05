"""Fail-closed OpenRouter endpoint-catalog preflight for the pinned profile."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import socket
from dataclasses import dataclass
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from core.providers.agentic_protocol import AgenticModelRequest, EphemeralCredential
from core.providers.openrouter_agentic_catalog_records import (
    catalog_identity,
    configured_upstream_id,
    find_model_record,
    find_zdr_record,
    positive_int,
    supports_tool_choice_none,
    validate_record,
)
from core.providers.openrouter_agentic_models import (
    OPENROUTER_AGENTIC_MODEL_ID,
    OpenRouterAgenticProtocolError,
)
from core.providers.openrouter_agentic_request import openrouter_chat_payload
from core.providers.openrouter_agentic_state import decode_openrouter_chat_state
from core.runtime.execution_binding import canonical_digest
from core.runtime.hosted_agentic_budget import estimate_hosted_request_tokens


OPENROUTER_AGENTIC_ENDPOINT_CATALOG = (
    "https://openrouter.ai/api/v1/models/"
    f"{OPENROUTER_AGENTIC_MODEL_ID}/endpoints"
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
    upstream_provider_names: tuple[str, ...] = (),
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
            _model_endpoint_catalog_url(request.model_id),
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
        upstream_provider_names=upstream_provider_names,
    )


def validate_openrouter_agentic_catalog(
    request: AgenticModelRequest,
    *,
    model_catalog: object,
    zdr_catalog: object,
    upstream_provider_names: tuple[str, ...] = (),
) -> OpenRouterAgenticCatalogSnapshot:
    """Require the exact configured endpoint and every routed parameter."""
    if (
        not str(request.model_id or "").strip()
        or request.model_revision_policy != "provider_alias"
        or not str(request.model_revision or "").strip()
    ):
        raise OpenRouterAgenticProtocolError("provider_request_invalid")
    upstream_id = configured_upstream_id(request)
    quantizations = frozenset(request.routing_constraint.allowed_quantizations)
    model_record = find_model_record(
        model_catalog,
        model_id=request.model_id,
        upstream_id=upstream_id,
    )
    zdr_record = find_zdr_record(
        zdr_catalog,
        model_id=request.model_id,
        upstream_id=upstream_id,
    )
    required = _required_supported_parameters(request)
    required_context_tokens = (
        estimate_hosted_request_tokens(request) + request.max_output_tokens
    )
    model_parameters = validate_record(
        model_record,
        required=required,
        max_output_tokens=request.max_output_tokens,
        required_context_tokens=required_context_tokens,
        upstream_provider_names=upstream_provider_names,
        quantizations=quantizations,
    )
    zdr_parameters = validate_record(
        zdr_record,
        required=required,
        max_output_tokens=request.max_output_tokens,
        required_context_tokens=required_context_tokens,
        upstream_provider_names=upstream_provider_names,
        quantizations=quantizations,
    )
    if model_record.get("provider_name") != zdr_record.get("provider_name"):
        raise OpenRouterAgenticProtocolError(
            "provider_endpoint_parameters_unsupported"
        )
    model_none = supports_tool_choice_none(model_record)
    zdr_none = supports_tool_choice_none(zdr_record)
    if not model_none or not zdr_none:
        raise OpenRouterAgenticProtocolError(
            "provider_endpoint_parameters_unsupported"
        )
    model_context = positive_int(model_record.get("context_length"))
    zdr_context = positive_int(zdr_record.get("context_length"))
    model_completion = positive_int(model_record.get("max_completion_tokens"))
    zdr_completion = positive_int(zdr_record.get("max_completion_tokens"))
    snapshot_payload = {
        "upstream_id": upstream_id,
        "supported_parameters": tuple(sorted(model_parameters & zdr_parameters)),
        "model_catalog_record_digest": canonical_digest(
            catalog_identity(model_record, model_id=request.model_id)
        ),
        "zdr_catalog_record_digest": canonical_digest(
            catalog_identity(zdr_record, model_id=request.model_id)
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


def _model_endpoint_catalog_url(model_id: str) -> str:
    normalized = str(model_id or "").strip()
    path_segments = normalized.split("/")
    if any(not segment or segment in {".", ".."} for segment in path_segments):
        raise OpenRouterAgenticProtocolError("provider_request_invalid")
    encoded = "/".join(
        urllib_parse.quote(segment, safe="") for segment in path_segments
    )
    return f"https://openrouter.ai/api/v1/models/{encoded}/endpoints"


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


__all__ = [
    "OpenRouterAgenticCatalogSnapshot",
    "preflight_openrouter_agentic_catalog",
    "validate_openrouter_agentic_catalog",
]
