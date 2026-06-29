"""Provider routing fallback and policy decision tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import unittest

from core.providers.models import ProviderCredentialBinding, WorkspaceProviderPolicy
from core.providers.provider_credentials import bind_provider_credential
from core.providers.provider_registry import ProviderRegistry
from core.providers.routing import ProviderRoutingContext, select_provider_for_profile
from core.providers.service import builtin_provider_registry, configure_workspace_provider
from core.providers.store import ProviderCollections, ProviderDocumentStore
from tests.support.collections import FakeCollection


class ProviderRoutingFallbackTest(unittest.TestCase):
    def make_provider_store(self) -> ProviderDocumentStore:
        return ProviderDocumentStore(
            ProviderCollections(
                definitions=FakeCollection(),
                bindings=FakeCollection(),
                selections=FakeCollection(),
            )
        )

    def active_fast_registry(self) -> ProviderRegistry:
        registry = builtin_provider_registry()
        openrouter = registry.get_provider_definition("openrouter")
        registry.register_provider_definition(replace(openrouter, status="active"))
        return registry

    def test_fast_model_missing_credential_returns_auditable_failure(self) -> None:
        decision = select_provider_for_profile(
            "fast_model",
            ProviderRoutingContext(
                workspace_id="default",
                provider_store=self.make_provider_store(),
                registry=self.active_fast_registry(),
                request_id="req-missing",
            ),
        )

        self.assertIsNone(decision.selected_provider_id)
        self.assertIsNone(decision.execution_path)
        self.assertTrue(decision.credential_authorization_required)
        self.assertFalse(decision.fallback_used)
        self.assertIn("fallback_no_credential_authorization", decision.reason_codes)
        self.assertIn("no_fast_model_available", decision.reason_codes)

    def test_fast_model_does_not_select_legacy_provider_secret_ref_binding(self) -> None:
        store = self.make_provider_store()
        now = datetime(2026, 6, 22, 12, 0, tzinfo=UTC)
        store.save_provider_binding(
            ProviderCredentialBinding(
                binding_id="legacy-openrouter",
                provider_id="openrouter",
                workspace_id="default",
                secret_ref="platform:providers/openrouter",
                label="Legacy OpenRouter",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )

        decision = select_provider_for_profile(
            "fast_model",
            ProviderRoutingContext(
                workspace_id="default",
                provider_store=store,
                registry=self.active_fast_registry(),
                request_id="req-legacy",
            ),
        )

        self.assertIsNone(decision.selected_provider_id)
        self.assertIsNone(decision.execution_path)
        self.assertIn("provider_credential_binding_invalid_secret_ref", decision.reason_codes)
        self.assertIn("fallback_no_credential_authorization", decision.reason_codes)
        self.assertNotIn("platform:providers/openrouter", str(decision))

    def test_disabled_provider_is_not_selected(self) -> None:
        decision = select_provider_for_profile(
            "fast_model",
            ProviderRoutingContext(
                workspace_id="default",
                provider_store=self.make_provider_store(),
                registry=builtin_provider_registry(),
            ),
        )

        self.assertEqual(decision.candidate_provider_ids, ["google-ai-studio", "openrouter"])
        self.assertIsNone(decision.selected_provider_id)
        self.assertIn("provider_disabled:google-ai-studio", decision.reason_codes)
        self.assertIn("provider_disabled:openrouter", decision.reason_codes)
        self.assertIn("provider_disabled:openrouter", decision.reason_codes)

    def test_tier_policy_can_deny_free_and_allow_premium(self) -> None:
        store = self.make_provider_store()
        bind_provider_credential(
            store,
            provider_id="openrouter",
            workspace_id="default",
            secret_ref="platform:secret-alias/openrouter",
        )
        policy = WorkspaceProviderPolicy(
            workspace_id="default",
            plan_or_tier_rules={
                "free": {"allowed_provider_ids": ["google-ai-studio"]},
                "premium": {"allowed_provider_ids": ["openrouter"]},
            },
        )

        free_decision = select_provider_for_profile(
            "fast_model",
            ProviderRoutingContext(
                workspace_id="default",
                provider_store=store,
                registry=self.active_fast_registry(),
                policy=policy,
                user_tier="free",
            ),
        )
        premium_decision = select_provider_for_profile(
            "fast_model",
            ProviderRoutingContext(
                workspace_id="default",
                provider_store=store,
                registry=self.active_fast_registry(),
                policy=policy,
                user_tier="premium",
            ),
        )

        self.assertIsNone(free_decision.selected_provider_id)
        self.assertIn("workspace_policy_denied:openrouter", free_decision.reason_codes)
        self.assertEqual(premium_decision.selected_provider_id, "openrouter")

    def test_codex_fallback_requires_explicit_flag(self) -> None:
        explicit = select_provider_for_profile(
            "fast_model",
            ProviderRoutingContext(
                workspace_id="default",
                provider_store=self.make_provider_store(),
                registry=self.active_fast_registry(),
                allow_fallback_codex=True,
            ),
        )
        implicit = select_provider_for_profile(
            "fast_model",
            ProviderRoutingContext(
                workspace_id="default",
                provider_store=self.make_provider_store(),
                registry=self.active_fast_registry(),
            ),
        )

        self.assertTrue(explicit.fallback_used)
        self.assertEqual(explicit.selected_runtime_engine_id, "codex")
        self.assertEqual(explicit.execution_path, "agentic_runtime")
        self.assertIn("fallback_codex_explicit", explicit.reason_codes)
        self.assertFalse(implicit.fallback_used)

    def test_heavy_runtime_uses_configured_codex_selection(self) -> None:
        store = self.make_provider_store()
        registry = builtin_provider_registry()
        configure_workspace_provider(
            store,
            workspace_id="default",
            provider_id="codex",
            registry=registry,
        )

        decision = select_provider_for_profile(
            "heavy_runtime",
            ProviderRoutingContext(
                workspace_id="default",
                provider_store=store,
                registry=registry,
            ),
        )

        self.assertEqual(decision.selected_provider_id, "codex")
        self.assertEqual(decision.selected_runtime_engine_id, "codex")
        self.assertEqual(decision.execution_path, "agentic_runtime")
        self.assertIn("runtime_engine_remains_codex", decision.reason_codes)


if __name__ == "__main__":
    unittest.main()
