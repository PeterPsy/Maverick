"""Provider routing decision tests."""

from __future__ import annotations

from dataclasses import replace
import unittest

from core.providers.models import WorkspaceProviderPolicy
from core.providers.provider_credentials import bind_provider_credential
from core.providers.provider_registry import ProviderRegistry
from core.providers.routing import ProviderRoutingContext, select_provider_for_profile
from core.providers.service import builtin_provider_registry, configure_workspace_provider
from core.providers.store import ProviderCollections, ProviderDocumentStore
from tests.support.collections import FakeCollection


class ProviderRoutingTest(unittest.TestCase):
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
        groq = registry.get_provider_definition("groq")
        registry.register_provider_definition(replace(groq, status="active"))
        return registry

    def test_fast_model_selects_active_provider_with_binding(self) -> None:
        store = self.make_provider_store()
        bind_provider_credential(
            store,
            provider_id="groq",
            workspace_id="default",
            secret_ref="platform:providers/groq",
        )

        decision = select_provider_for_profile(
            "fast_model",
            ProviderRoutingContext(
                workspace_id="default",
                provider_store=store,
                registry=self.active_fast_registry(),
                request_id="req-1",
            ),
        )

        self.assertEqual(decision.request_id, "req-1")
        self.assertEqual(decision.selected_provider_id, "groq")
        self.assertEqual(decision.selected_model_id_or_voice_id, "llama-3.3-70b-versatile")
        self.assertEqual(decision.execution_path, "plain_hosted_text")
        self.assertTrue(decision.credential_authorization_required)
        self.assertIsNotNone(decision.provider_credential_binding_id_optional)
        self.assertFalse(decision.fallback_used)
        self.assertIn("plain_hosted_text_selected", decision.reason_codes)
        self.assertNotIn("platform:providers/groq", str(decision))

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

    def test_disabled_provider_is_not_selected(self) -> None:
        decision = select_provider_for_profile(
            "fast_model",
            ProviderRoutingContext(
                workspace_id="default",
                provider_store=self.make_provider_store(),
                registry=builtin_provider_registry(),
            ),
        )

        self.assertEqual(decision.candidate_provider_ids, ["groq"])
        self.assertIsNone(decision.selected_provider_id)
        self.assertIn("provider_disabled:groq", decision.reason_codes)

    def test_tier_policy_can_deny_free_and_allow_premium(self) -> None:
        store = self.make_provider_store()
        bind_provider_credential(
            store,
            provider_id="groq",
            workspace_id="default",
            secret_ref="platform:providers/groq",
        )
        policy = WorkspaceProviderPolicy(
            workspace_id="default",
            plan_or_tier_rules={
                "free": {"allowed_provider_ids": ["deepseek"]},
                "premium": {"allowed_provider_ids": ["groq"]},
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
        self.assertIn("workspace_policy_denied:groq", free_decision.reason_codes)
        self.assertEqual(premium_decision.selected_provider_id, "groq")

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
