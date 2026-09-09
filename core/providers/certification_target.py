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


def certification_manifest_target(manifest) -> str:
    """Resolve the code-owned target for either supported certificate scope."""
    if manifest.target_scope == "api_profile":
        return builtin_api_certification_target(manifest.provider_id)
    if manifest.target_scope == "native_connection":
        from core.providers.native_agent_builtins import (
            build_antigravity_cli_candidate_installation,
        )

        if (
            manifest.provider_id != "antigravity-cli"
            or manifest.model_provider_id != "google"
        ):
            raise CapabilityCertificateError("certification_target_unknown")
        return native_connection_target_digest(
            build_antigravity_cli_candidate_installation(),
            model_provider_id=manifest.model_provider_id,
        )
    raise CapabilityCertificateError("certification_target_family_invalid")


def certification_manifest_reasoning_efforts(manifest) -> tuple[str, ...]:
    if manifest.target_scope == "api_profile":
        return builtin_api_reasoning_efforts(manifest.provider_id)
    efforts = tuple(manifest.behavioral_reasoning_efforts)
    if not efforts:
        raise CapabilityCertificateError("certification_behavior_reasoning_mismatch")
    return efforts


def certification_manifest_resource_limits(manifest) -> dict[str, int]:
    if manifest.target_scope == "api_profile":
        return api_certification_resource_limits(
            builtin_api_certification_profile(manifest.provider_id)
        )
    limits = dict(manifest.behavioral_resource_limits)
    if not limits or any(
        not isinstance(key, str)
        or not key
        or type(value) is not int
        or value < 1
        for key, value in limits.items()
    ):
        raise CapabilityCertificateError("certification_behavior_resource_invalid")
    return limits


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
