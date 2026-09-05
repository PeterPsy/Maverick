"""Immutable endpoint, routing, and accounting data for Maverick Agents."""

from __future__ import annotations

from dataclasses import dataclass
import math
from urllib.parse import urlsplit

from core.providers.agentic_models import RoutingConstraint
from core.providers.errors import AgenticProfileError
from core.runtime.execution_binding import canonical_digest


@dataclass(frozen=True)
class MaverickTokenCostPolicy:
    """Versioned token pricing used for reservations and reported usage."""

    policy_id: str
    revision: str
    input_microusd_per_million_tokens: int
    output_microusd_per_million_tokens: int
    estimated_input_bytes_per_token: int = 3

    @property
    def digest(self) -> str:
        return canonical_digest(self)

    def usage_cost_microusd(self, input_tokens: int, output_tokens: int) -> int:
        if not _nonnegative_int(input_tokens) or not _nonnegative_int(output_tokens):
            raise ValueError("maverick_usage_tokens_invalid")
        total = (
            input_tokens * self.input_microusd_per_million_tokens
            + output_tokens * self.output_microusd_per_million_tokens
        )
        return math.ceil(total / 1_000_000)

    def request_ceiling_microusd(self, request: object) -> int:
        input_bytes = sum(
            len(block.content) for block in getattr(request, "content_blocks", ())
        )
        input_bytes += sum(
            len(result.content) for result in getattr(request, "tool_results", ())
        )
        input_bytes += sum(
            len(tool.name) + len(tool.description) + len(str(tool.input_schema))
            for tool in getattr(request, "tool_definitions", ())
        )
        private_state = getattr(request, "provider_private_state", None)
        if private_state is not None:
            input_bytes += len(private_state.content)
        estimated_input_tokens = max(
            1,
            math.ceil(input_bytes / self.estimated_input_bytes_per_token),
        )
        return self.usage_cost_microusd(
            estimated_input_tokens,
            int(getattr(request, "max_output_tokens")),
        )


@dataclass(frozen=True)
class MaverickProviderConfig:
    """Endpoint, upstream, credential, and data policy for one provider."""

    config_id: str
    revision: str
    model_provider_id: str
    provider_protocol: str
    provider_api_version: str | None
    routing_constraint: RoutingConstraint
    endpoint_url: str
    credential_logical_name: str
    data_destination: str
    retention_policy: str
    token_cost_policy: MaverickTokenCostPolicy
    upstream_provider_names: tuple[str, ...] = ()
    resolved_model_ids: tuple[str, ...] = ()

    @property
    def digest(self) -> str:
        return canonical_digest(self)


def validate_maverick_provider_config(config: MaverickProviderConfig) -> None:
    """Reject incomplete routes, non-HTTPS endpoints, and invalid pricing."""
    if (
        not isinstance(config, MaverickProviderConfig)
        or not isinstance(config.routing_constraint, RoutingConstraint)
        or not isinstance(config.token_cost_policy, MaverickTokenCostPolicy)
    ):
        raise AgenticProfileError("maverick_provider_config_incomplete")
    pricing = config.token_cost_policy
    identity_fields = (
        config.config_id,
        config.revision,
        config.model_provider_id,
        config.provider_protocol,
        config.routing_constraint.endpoint_id,
        config.endpoint_url,
        config.credential_logical_name,
        config.data_destination,
        config.retention_policy,
        pricing.policy_id,
        pricing.revision,
    )
    if any(
        not isinstance(value, str) or not value or value.strip() != value
        for value in identity_fields
    ) or (
        config.provider_api_version is not None
        and (
            not isinstance(config.provider_api_version, str)
            or not config.provider_api_version
            or config.provider_api_version.strip() != config.provider_api_version
        )
    ):
        raise AgenticProfileError("maverick_provider_config_incomplete")
    try:
        endpoint = urlsplit(config.endpoint_url)
        hostname = endpoint.hostname
        port = endpoint.port
    except (TypeError, ValueError) as error:
        raise AgenticProfileError("maverick_provider_endpoint_invalid") from error
    if (
        config.endpoint_url != config.endpoint_url.strip()
        or endpoint.scheme != "https"
        or not hostname
        or port is not None
        or endpoint.username is not None
        or endpoint.password is not None
        or endpoint.fragment
    ):
        raise AgenticProfileError("maverick_provider_endpoint_invalid")
    routing = config.routing_constraint
    upstream_ids = tuple(
        str(value or "").strip() for value in routing.allowed_upstream_ids
    )
    provider_names = tuple(
        str(value or "").strip() for value in config.upstream_provider_names
    )
    resolved_models = tuple(
        str(value or "").strip() for value in config.resolved_model_ids
    )
    if (
        upstream_ids != routing.allowed_upstream_ids
        or any(not value for value in upstream_ids)
        or len(set(upstream_ids)) != len(upstream_ids)
        or provider_names != config.upstream_provider_names
        or len(provider_names) != len(upstream_ids)
        or any(not value for value in provider_names)
        or len(set(provider_names)) != len(provider_names)
        or resolved_models != config.resolved_model_ids
        or any(not value for value in resolved_models)
        or len(set(resolved_models)) != len(resolved_models)
    ):
        raise AgenticProfileError("maverick_provider_routing_invalid")
    if (
        not _nonnegative_int(pricing.input_microusd_per_million_tokens)
        or not _nonnegative_int(pricing.output_microusd_per_million_tokens)
        or not _positive_int(pricing.estimated_input_bytes_per_token)
    ):
        raise AgenticProfileError("maverick_provider_pricing_invalid")


def _nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


__all__ = [
    "MaverickProviderConfig",
    "MaverickTokenCostPolicy",
    "validate_maverick_provider_config",
]
