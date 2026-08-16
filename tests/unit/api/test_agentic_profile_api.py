"""Agentic profile control-plane payload tests."""

from __future__ import annotations

import json
from types import SimpleNamespace
import unittest

from core.api.provider_api import workspace_provider_status
from core.providers.service import (
    builtin_provider_registry,
    configure_workspace_provider,
    register_builtin_providers,
)
from core.providers.agentic_profiles import build_pinned_execution_binding
from core.providers.store import ProviderCollections, ProviderDocumentStore
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


if __name__ == "__main__":
    unittest.main()
