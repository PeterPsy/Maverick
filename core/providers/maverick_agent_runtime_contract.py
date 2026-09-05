"""Executable composition checks for one Maverick Agent publication."""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING

from core.providers.errors import AgenticProfileError
from core.providers.maverick_agent_provider_config import MaverickTokenCostPolicy
from core.runtime.hosted_agentic_models import HostedFinalizationPolicy, HostedProviderPrivateCodec
from core.runtime.hosted_provider_runtime import HostedProviderRuntime

if TYPE_CHECKING:
    from core.providers.maverick_agent_onboarding import (
        MaverickAgentProfilePublication,
    )


def validate_composed_maverick_runtime(
    publication: MaverickAgentProfilePublication,
    runtime: HostedProviderRuntime,
) -> None:
    """Prove that a factory made the endpoint and accounting it declared."""
    adapter = publication.adapter
    config = publication.provider_config
    recipe = publication.recipe
    client = runtime.client
    expected_runtime_identity = {
        "model_provider_id": config.model_provider_id,
        "provider_protocol": config.provider_protocol,
        "provider_api_version": config.provider_api_version,
        "provider_config_id": config.config_id,
        "provider_config_revision": config.revision,
        "provider_config_digest": config.digest,
        "protocol_adapter_id": adapter.protocol_adapter_id,
        "protocol_adapter_version": adapter.protocol_adapter_version,
        "endpoint_id": config.routing_constraint.endpoint_id,
        "endpoint_url": config.endpoint_url,
        "allowed_upstream_ids": config.routing_constraint.allowed_upstream_ids,
    }
    if runtime.recipe != recipe or any(
        getattr(runtime, field_name) != value
        for field_name, value in expected_runtime_identity.items()
    ):
        raise AgenticProfileError("maverick_runtime_identity_mismatch")
    client_identity = {
        "model_id": recipe.model_id,
        "endpoint_url": config.endpoint_url,
        "routing_constraint": config.routing_constraint,
        "allowed_upstream_ids": config.routing_constraint.allowed_upstream_ids,
        "upstream_provider_names": config.upstream_provider_names,
        "resolved_model_ids": config.resolved_model_ids,
    }
    if any(
        getattr(client, field_name, None) != value
        for field_name, value in client_identity.items()
    ):
        raise AgenticProfileError("maverick_runtime_transport_identity_mismatch")
    if (
        getattr(client, "token_cost_policy", None) is not config.token_cost_policy
        or getattr(runtime.cost_estimator, "__self__", None)
        is not config.token_cost_policy
        or getattr(runtime.cost_estimator, "__func__", None)
        is not MaverickTokenCostPolicy.request_ceiling_microusd
    ):
        raise AgenticProfileError("maverick_runtime_accounting_identity_mismatch")
    if runtime.implementation_manifest != adapter:
        raise AgenticProfileError("maverick_runtime_implementation_mismatch")
    create_response = getattr(client, "create_response", None)
    if not callable(create_response):
        raise AgenticProfileError("maverick_runtime_client_incomplete")
    try:
        inspect.signature(create_response).bind(object(), credential=None)
    except (TypeError, ValueError) as error:
        raise AgenticProfileError("maverick_runtime_client_incomplete") from error
    if not isinstance(runtime.private_codec, HostedProviderPrivateCodec) or (
        f"{runtime.private_codec.codec_id}@{runtime.private_codec.codec_version}"
        != adapter.private_state_codec_id
    ):
        raise AgenticProfileError("maverick_runtime_private_codec_mismatch")
    if not all(callable(component) for component in (
        runtime.private_state_inspector,
        runtime.context_compactor,
        runtime.request_preflight,
    )):
        raise AgenticProfileError("maverick_runtime_recovery_incomplete")
    if not isinstance(runtime.finalization_policy, HostedFinalizationPolicy):
        raise AgenticProfileError("maverick_runtime_finalization_incomplete")


__all__ = ["validate_composed_maverick_runtime"]
