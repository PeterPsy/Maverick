"""Content identities for the distinct API-profile and native-connection scopes."""

from dataclasses import asdict

from core.providers.errors import CapabilityCertificateError
from core.runtime.execution_binding import canonical_digest


def api_profile_target_digest(definition) -> str:
    """Bind every immutable policy/config/model field, not its publication time."""
    if definition.execution_family != "maverick_agent":
        raise CapabilityCertificateError("certification_target_family_invalid")
    payload = asdict(definition)
    payload.pop("created_at")
    return canonical_digest({"scope": "api_profile", "definition": payload})


def builtin_api_certification_target(provider_id: str) -> str:
    return api_profile_target_digest(builtin_api_certification_profile(provider_id))


def builtin_api_certification_profile(provider_id: str):
    from core.providers.maverick_agent_builtins import builtin_maverick_agent_publications

    targets = [publication.profile for publication in builtin_maverick_agent_publications()
               if publication.profile.model_provider_id == provider_id]
    if len(targets) != 1:
        raise CapabilityCertificateError("certification_target_unknown")
    return targets[0]


def builtin_api_reasoning_efforts(provider_id: str) -> tuple[str, ...]:
    from core.providers.maverick_agent_builtins import builtin_maverick_agent_publications

    return next(publication.recipe.support_flags.reasoning_efforts
                for publication in builtin_maverick_agent_publications()
                if publication.profile.model_provider_id == provider_id)


def api_certification_resource_limits(definition) -> dict[str, int]:
    policy = definition.policy_ceiling
    return {
        "input_tokens": policy.max_input_tokens,
        "output_tokens": policy.max_output_tokens,
        "tool_calls": policy.max_tool_calls_per_turn,
        "provider_steps": policy.max_steps_per_turn,
        "wall_time_ms": policy.max_wall_time_seconds * 1_000,
        "cost_microusd": policy.max_estimated_cost_microusd,
    }


def native_connection_target_digest(installation, *, model_provider_id: str) -> str:
    """Model slugs are intentionally absent: native certification is per connection."""
    from core.providers.native_agent_contract import validate_native_agent_installation

    validate_native_agent_installation(installation)
    connections = [item for item in installation.model_provider_connections
                   if item.model_provider_id == model_provider_id]
    if len(connections) != 1 or installation.runtime_artifact is None:
        raise CapabilityCertificateError("certification_native_target_incomplete")
    if not installation.certificate.full_workspace_contract_revision:
        raise CapabilityCertificateError("certification_native_target_incomplete")
    return canonical_digest({
        "scope": "native_connection", "manifest": installation.manifest,
        "recipe": installation.recipe, "connection": connections[0],
        "effects": installation.effects, "runtime_artifact": installation.runtime_artifact,
        "full_workspace_contract_revision": installation.certificate.full_workspace_contract_revision,
    })
