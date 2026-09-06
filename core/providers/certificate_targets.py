"""Enforce the immutable API-profile target after certificate publication."""

from core.providers.capability_models import CapabilityCertificate
from core.providers.certification_target import api_profile_target_digest
from core.providers.errors import CapabilityCertificateError, ProviderNotFoundError


def validate_api_certificate_target_shape(certificate: CapabilityCertificate) -> None:
    target = certificate.certification_target_digest
    if certificate.execution_family == "maverick_agent":
        if not isinstance(target, str) or len(target) != 64 or any(
            character not in "0123456789abcdef" for character in target
        ):
            raise CapabilityCertificateError("certificate_target_missing_or_invalid")
    elif target:
        # Native certificates are connection-scoped, never API-profile-scoped.
        raise CapabilityCertificateError("certificate_target_family_invalid")


def validate_api_profile_certificate_target(*, profile, certificate) -> None:
    """Missing historical API targets fail closed; never backfill from a profile."""
    validate_api_certificate_target_shape(certificate)
    profile_family = getattr(profile, "execution_family", "")
    if profile_family != "maverick_agent" and certificate.execution_family != "maverick_agent":
        return
    if (
        profile_family != "maverick_agent"
        or certificate.execution_family != "maverick_agent"
        or profile.capability_certificate_id != certificate.certificate_id
        or api_profile_target_digest(profile) != certificate.certification_target_digest
    ):
        raise CapabilityCertificateError("certificate_target_mismatch")


def validate_api_binding_certificate_target(store, *, binding, certificate) -> None:
    """Recheck the stored target and the actual policy/config snapshots in a pin."""
    validate_api_certificate_target_shape(certificate)
    if binding.execution_family != "maverick_agent" and certificate.execution_family != "maverick_agent":
        return
    try:
        profile = store.get_agentic_profile_definition(
            binding.profile_definition_id, binding.profile_definition_revision,
        )
    except ProviderNotFoundError as error:
        raise CapabilityCertificateError("certificate_target_profile_missing") from error
    validate_api_profile_certificate_target(profile=profile, certificate=certificate)
    fields = (
        "runtime_engine_id", "adapter_id", "model_provider_id", "model_id",
        "model_revision", "model_revision_policy", "provider_protocol", "provider_api_version",
        "full_workspace_contract_revision", "execution_family", "harness_recipe_id",
        "harness_recipe_revision", "harness_recipe_digest", "provider_capability_catalog_digest",
        "semantic_projection_compiler_revision", "tool_contract_revision", "provider_config_id",
        "provider_config_revision", "provider_config_digest", "protocol_adapter_id", "protocol_adapter_version",
    )
    expected = {name: getattr(profile, name) for name in fields}
    expected.update(
        capability_certificate_id=profile.capability_certificate_id,
        routing_constraint_snapshot=profile.routing_constraint,
        profile_policy_ceiling_snapshot=profile.policy_ceiling,
        context_policy_snapshot=profile.context_policy,
    )
    if profile.adapter_version_constraint != f"=={binding.adapter_version}" or any(
        getattr(binding, name) != value for name, value in expected.items()
    ):
        raise CapabilityCertificateError("certificate_target_binding_mismatch")
    # Workspace ceilings/egress are governed separately and may narrow the profile.
