"""Agentic profile control-plane payload tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from dataclasses import replace
from types import SimpleNamespace
import unittest

from core.api.provider_api import workspace_provider_status
from core.api.runtime_api import _session_payload
from core.providers.service import (
    builtin_provider_registry,
    configure_workspace_provider,
    register_builtin_providers,
)
from core.providers.agentic_profiles import build_pinned_execution_binding
from core.providers.agentic_models import ActorSelectionPolicy
from core.providers.store import ProviderCollections, ProviderDocumentStore
from core.runtime.runtime_session import RuntimeSessionRecord
from tests.support.collections import FakeCollection


class AgenticProfileApiTest(unittest.TestCase):
    def test_status_exposes_redaction_safe_per_session_profiles(self) -> None:
        provider_store = ProviderDocumentStore(
            ProviderCollections(
                definitions=FakeCollection(),
                bindings=FakeCollection(),
                selections=FakeCollection(),
            )
        )
        registry = builtin_provider_registry()
        register_builtin_providers(provider_store, registry=registry)
        configure_workspace_provider(
            provider_store,
            workspace_id="default",
            provider_id="codex",
        )
        build_pinned_execution_binding(
            provider_store,
            registry,
            session_id="session-certified-api",
            workspace_id="default",
            execution_mode="sandbox",
        )
        state = SimpleNamespace(provider_store=provider_store, secret_store=None)

        payload = workspace_provider_status(state, workspace_id="default")

        profile = payload["agentic_profiles"]["items"][0]
        self.assertEqual(profile["runtime_engine_id"], "codex")
        self.assertEqual(
            payload["agentic_profiles"]["default_binding_id"],
            profile["workspace_profile_binding_id"],
        )
        encoded = json.dumps(profile, default=str)
        self.assertNotIn("credential_binding_id", encoded)
        self.assertNotIn("secret_ref", encoded)
        self.assertTrue(profile["certified"])
        self.assertEqual(profile["certificate"]["effective_status"], "active")

        runtime_binding = build_pinned_execution_binding(
            provider_store,
            registry,
            session_id="session-public-payload",
            workspace_id="default",
            execution_mode="sandbox",
        )
        session = RuntimeSessionRecord(
            session_id="session-public-payload",
            workspace_id="default",
            agent_id="chat",
            status="running",
            requested_mode="sandbox",
            effective_mode="sandbox",
            workspace_root="/workspace",
            workdir="/workspace",
            runtime_root="/runtime",
            started_at=datetime(2026, 8, 16, tzinfo=UTC),
            updated_at=datetime(2026, 8, 16, tzinfo=UTC),
            ended_at=None,
            last_progress_at=None,
            execution_binding=runtime_binding,
        )
        serialized_session = json.dumps(
            _session_payload(session, provider_id="codex"),
            default=str,
        )
        self.assertNotIn("credential_binding_id", serialized_session)
        self.assertIn("profile_definition_revision", serialized_session)

    def test_status_only_projects_profiles_selectable_by_the_human_actor(self) -> None:
        provider_store = ProviderDocumentStore(
            ProviderCollections(
                definitions=FakeCollection(),
                bindings=FakeCollection(),
                selections=FakeCollection(),
            )
        )
        registry = builtin_provider_registry()
        register_builtin_providers(provider_store, registry=registry)
        configure_workspace_provider(
            provider_store,
            workspace_id="default",
            provider_id="codex",
        )
        binding = provider_store.list_workspace_agentic_profile_bindings("default")[0]
        provider_store.save_workspace_agentic_profile_binding(
            replace(
                binding,
                actor_policy=ActorSelectionPolicy(
                    allow_workspace_admins=True,
                    allowed_user_ids=(),
                    allowed_workspace_role_ids=(),
                    allowed_agent_type_ids=(),
                ),
                revision=binding.revision + 1,
            ),
            expected_revision=binding.revision,
        )
        state = SimpleNamespace(provider_store=provider_store, secret_store=None)

        member_payload = workspace_provider_status(
            state,
            workspace_id="default",
            actor_roles=("member", "member-1", "member"),
        )
        admin_payload = workspace_provider_status(
            state,
            workspace_id="default",
            actor_roles=("admin", "admin-1", "admin"),
        )

        self.assertEqual(member_payload["agentic_profiles"]["items"], [])
        self.assertEqual(len(admin_payload["agentic_profiles"]["items"]), 1)


if __name__ == "__main__":
    unittest.main()
