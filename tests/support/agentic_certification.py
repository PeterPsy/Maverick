"""Deterministic certification fixtures for agentic runtime tests."""

from __future__ import annotations

from datetime import datetime, timedelta

from core.providers.agentic_models import (
    AgenticProfileDefinitionStatus,
    WorkspaceAgenticProfileBinding,
    default_actor_selection_policy,
)
from core.providers.capability_models import CapabilityCertificate, RuntimeCapabilitySet
from core.providers.certificate_service import (
    build_capability_evidence,
    publish_capability_certificate,
    runtime_adapter_artifact_digest,
)
from core.providers.store import ProviderCollections, ProviderDocumentStore
from core.runtime.authority import resolve_effective_runtime_authority
from core.runtime.execution_binding import RuntimeExecutionBinding, canonical_digest
from tests.support.collections import FakeCollection


def fake_capability_evidence(adapter: object, *, now: datetime):
    artifact_digest = runtime_adapter_artifact_digest(adapter)
    return build_capability_evidence(
        suite_id="fake-agentic-contract",
        suite_version="1",
        test_run_id=f"fake-run:{artifact_digest[:16]}",
        adapter_artifact_digest=artifact_digest,
        result_summary_digest=canonical_digest({"result": "passed"}),
        evidence_refs=("platform-evidence:test:fake-agentic-contract",),
        recorded_at=now,
    )


def certified_test_provider_store(
    binding: RuntimeExecutionBinding,
    adapter: object,
    *,
    evidence,
    now: datetime,
    validity_days: int = 1,
) -> ProviderDocumentStore:
    store = ProviderDocumentStore(
        ProviderCollections(
            definitions=FakeCollection(),
            bindings=FakeCollection(),
            selections=FakeCollection(),
            agentic_profile_definition_statuses=FakeCollection(),
            workspace_agentic_profile_bindings=FakeCollection(),
            capability_evidence=FakeCollection(),
            capability_certificates=FakeCollection(),
            capability_certificate_statuses=FakeCollection(),
        )
    )
    store.save_agentic_profile_definition_status(
        AgenticProfileDefinitionStatus(
            definition_id=binding.profile_definition_id,
            definition_revision=binding.profile_definition_revision,
            rollout_status="preview",
            revision=0,
            updated_at=now,
        ),
        expected_revision=None,
    )
    store.save_workspace_agentic_profile_binding(
        WorkspaceAgenticProfileBinding(
            binding_id=binding.workspace_binding_id,
            workspace_id=binding.workspace_id,
            definition_id=binding.profile_definition_id,
            definition_revision=binding.profile_definition_revision,
            credential_binding_id=binding.credential_binding_id,
            enabled=True,
            is_default=True,
            actor_policy=default_actor_selection_policy(),
            workspace_policy_ceiling=binding.workspace_policy_ceiling_snapshot,
            egress_policy_id=binding.egress_policy_id,
            egress_policy_revision=binding.egress_policy_revision,
            revision=binding.workspace_binding_revision,
            created_at=now,
            updated_at=now,
        ),
        expected_revision=None,
    )
    publish_capability_certificate(
        store,
        evidence=evidence,
        certificate=CapabilityCertificate(
            certificate_id=binding.capability_certificate_id,
            schema_version="1",
            runtime_engine_id=binding.runtime_engine_id,
            adapter_id=binding.adapter_id,
            adapter_version=binding.adapter_version,
            adapter_artifact_digest=binding.adapter_artifact_digest,
            model_provider_id=binding.model_provider_id,
            model_id=binding.model_id,
            model_revision=None,
            provider_protocol=binding.provider_protocol,
            provider_api_version=binding.provider_api_version,
            certified_upstream_ids=binding.routing_constraint_snapshot.allowed_upstream_ids,
            routing_constraint_digest=canonical_digest(binding.routing_constraint_snapshot),
            certified_capabilities=RuntimeCapabilitySet(
                streaming=True,
                tool_orchestration=True,
                cli=True,
                mcp=True,
                skill_catalog=True,
                filesystem_list=True,
                filesystem_read=True,
                filesystem_write=True,
                shell=True,
                interrupt=True,
                same_turn_steering=False,
                recovery=True,
                confirmation_resume=True,
                provider_private_state=True,
                attachment_modalities=(),
            ),
            certified_reasoning_efforts=binding.certified_reasoning_efforts,
            default_reasoning_effort=binding.default_reasoning_effort,
            suite_id=evidence.suite_id,
            suite_version=evidence.suite_version,
            test_run_id=evidence.test_run_id,
            evidence_digest=evidence.evidence_digest,
            evidence_refs=evidence.evidence_refs,
            issued_at=now,
            expires_at=now + timedelta(days=validity_days),
        ),
    )
    return store


def certified_test_authority(store, binding, adapter, *, turn_id: str, now: datetime):
    return resolve_effective_runtime_authority(
        store,
        binding=binding,
        adapter=adapter,
        turn_id=turn_id,
        now=now,
    )
