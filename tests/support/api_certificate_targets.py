"""Offline API-profile certificates for target enforcement, not release evidence."""

from core.providers.certification_target import builtin_api_certification_profile
from core.providers.google_agentic_certification import _capabilities
from core.runtime.execution_binding import build_runtime_execution_binding
from tests.support.agentic_certification import certified_test_provider_store, fake_capability_evidence
from tests.support.fake_agentic_adapter import FakeHostedAgenticAdapter


def api_certificate_fixture(provider_id, *, now):
    profile = builtin_api_certification_profile(provider_id)
    adapter = FakeHostedAgenticAdapter()
    adapter.runtime_engine_id = profile.runtime_engine_id
    adapter.adapter_id = profile.adapter_id
    adapter.adapter_version = profile.adapter_version_constraint.removeprefix("==")
    evidence = fake_capability_evidence(adapter, now=now, definition=profile)
    fields = (
        "runtime_engine_id", "adapter_id", "model_provider_id", "model_id",
        "model_revision", "model_revision_policy", "provider_protocol", "provider_api_version",
        "full_workspace_contract_revision", "execution_family", "harness_recipe_id",
        "harness_recipe_revision", "harness_recipe_digest", "provider_capability_catalog_digest",
        "semantic_projection_compiler_revision", "tool_contract_revision", "provider_config_id",
        "provider_config_revision", "provider_config_digest", "protocol_adapter_id", "protocol_adapter_version",
        "routing_constraint", "capability_certificate_id", "egress_policy_id", "egress_policy_revision",
        "context_policy",
    )
    binding = build_runtime_execution_binding(
        **{name: getattr(profile, name) for name in fields},
        session_id="target-session", workspace_id="default",
        profile_definition_id=profile.definition_id, profile_definition_revision=profile.revision,
        workspace_binding_id="target-workspace", workspace_binding_revision=0,
        adapter_version=adapter.adapter_version, adapter_artifact_digest=evidence.adapter_artifact_digest,
        certificate_evidence_digest=evidence.evidence_digest,
        credential_binding_id=None, reasoning_effort="high", certified_reasoning_efforts=("high",),
        default_reasoning_effort="high", execution_mode="full-access",
        profile_policy_ceiling=profile.policy_ceiling, workspace_policy_ceiling=profile.policy_ceiling,
        created_at=now,
    )
    store = certified_test_provider_store(
        binding, adapter, evidence=evidence, now=now, definition=profile,
        certified_capabilities=_capabilities(),
    )
    return profile, adapter, binding, store
