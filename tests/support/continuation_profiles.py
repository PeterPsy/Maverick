"""Publish exact-target API fixtures into an isolated continuation test store.

These unsigned, fake-adapter records are not built-in or release certificates.
Native connection identity is deliberately not rewritten to model API upgrades.
"""

from dataclasses import replace

from core.providers.certificate_service import publish_capability_certificate
from core.providers.certification_target import builtin_api_certification_profile
from tests.support.api_certificate_targets import api_certificate_fixture


def install_continuation_target(state, *, now, profile=None):
    profile = profile or replace(
        builtin_api_certification_profile("google-ai-studio"),
        definition_id="offline-continuation-profile",
        revision="current-fixture-v1",
        capability_certificate_id="offline-continuation-certificate",
        display_name="Offline continuation fixture",
        runtime_engine_id="offline-continuation-engine",
        adapter_id="offline-continuation-adapter",
        created_at=now,
    )
    profile, adapter, binding, fixture = api_certificate_fixture(
        "google-ai-studio", now=now, profile=profile, validity_days=365,
    )
    registry = state.provider_registry
    registry.register_agentic_runtime_adapter(adapter, definition=replace(
        registry.get_provider_definition("maverick-tool-loop"),
        provider_id=profile.runtime_engine_id,
    ))
    registry.register_provider_definition(replace(
        registry.get_provider_definition(profile.model_provider_id), requires_credentials=False,
    ))
    store = state.provider_store
    store.save_agentic_profile_definition(profile)
    store.save_agentic_profile_definition_status(
        fixture.get_agentic_profile_definition_status(profile.definition_id, profile.revision),
        expected_revision=None,
    )
    store.save_workspace_agentic_profile_binding(
        replace(fixture.get_workspace_agentic_profile_binding(binding.workspace_binding_id), is_default=False),
        expected_revision=None,
    )
    certificate = fixture.get_capability_certificate(binding.capability_certificate_id)
    publish_capability_certificate(
        store, certificate=certificate,
        evidence=fixture.get_capability_evidence(certificate.evidence_digest),
    )
    return binding
