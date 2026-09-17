"""Deterministic direct-profile fixtures for agentic runtime tests."""

from __future__ import annotations

from datetime import datetime

from core.providers.agentic_models import (
    AgenticProfileDefinitionStatus,
    WorkspaceAgenticProfileBinding,
    default_actor_selection_policy,
)
from core.providers.store import ProviderCollections, ProviderDocumentStore
from core.runtime.authority import resolve_runtime_authority
from core.runtime.execution_binding import RuntimeExecutionBinding
from tests.support.collections import FakeCollection


def direct_test_provider_store(
    binding: RuntimeExecutionBinding,
    *,
    now: datetime,
    definition=None,
) -> ProviderDocumentStore:
    """Build a store whose live policy accepts the binding's direct profile contract."""
    store = ProviderDocumentStore(
        ProviderCollections(
            definitions=FakeCollection(),
            agentic_profile_definitions=FakeCollection(),
            bindings=FakeCollection(),
            selections=FakeCollection(),
            agentic_profile_definition_statuses=FakeCollection(),
            workspace_agentic_profile_bindings=FakeCollection(),
        )
    )
    if definition is not None:
        store.save_agentic_profile_definition(definition)
    store.save_agentic_profile_definition_status(
        AgenticProfileDefinitionStatus(
            definition_id=binding.profile_definition_id,
            definition_revision=binding.profile_definition_revision,
            rollout_status="available",
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
    return store


def direct_test_authority(store, binding, adapter, *, turn_id: str, now: datetime):
    return resolve_runtime_authority(
        store,
        binding=binding,
        adapter=adapter,
        turn_id=turn_id,
        now=now,
    )
