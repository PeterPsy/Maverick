"""Provider routing decision tests."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from core.providers.payloads import routing_decision_payload
from core.providers.provider_credentials import bind_provider_credential
from core.providers.provider_registry import ProviderRegistry
from core.providers.routing import ProviderRoutingContext, select_provider_for_profile
from core.providers.service import (
    activate_hosted_model_provider,
    builtin_provider_registry,
    configure_hosted_model_provider,
    effective_provider_registry,
)
from core.providers.store import ProviderCollections, ProviderDocumentStore
from core.secrets.service import bind_provider_secret, build_secret_ref, create_platform_secret
from core.secrets.store import SecretCollections, SecretDocumentStore
from core.shared.json_file_collection import JsonFileCollection
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

    def make_json_provider_store(self, root: Path) -> ProviderDocumentStore:
        return ProviderDocumentStore(
            ProviderCollections(
                definitions=JsonFileCollection(root / "definitions.json"),
                bindings=JsonFileCollection(root / "bindings.json"),
                selections=JsonFileCollection(root / "selections.json"),
                hosted_selections=JsonFileCollection(root / "hosted_selections.json"),
            )
        )

    def make_secret_store(self) -> SecretDocumentStore:
        return SecretDocumentStore(
            SecretCollections(
                secrets=FakeCollection(),
                values=FakeCollection(),
                bindings=FakeCollection(),
                grants=FakeCollection(),
            ),
            key_loader=lambda: b"0" * 32,
        )

    def active_fast_registry(self) -> ProviderRegistry:
        return self.active_openrouter_registry()

    def active_openrouter_registry(self) -> ProviderRegistry:
        registry = builtin_provider_registry()
        openrouter = registry.get_provider_definition("openrouter")
        registry.register_provider_definition(replace(openrouter, status="active"))
        return registry

    def active_google_ai_studio_registry(self) -> ProviderRegistry:
        registry = builtin_provider_registry()
        google = registry.get_provider_definition("google-ai-studio")
        registry.register_provider_definition(replace(google, status="active"))
        return registry

    def test_fast_model_selects_active_provider_with_binding(self) -> None:
        store = self.make_provider_store()
        bind_provider_credential(
            store,
            provider_id="openrouter",
            workspace_id="default",
            secret_ref="platform:secret-alias/openrouter",
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
        self.assertEqual(decision.selected_provider_id, "openrouter")
        self.assertEqual(decision.selected_model_id_or_voice_id, "google/gemma-4-31b-it:free")
        self.assertEqual(decision.execution_path, "plain_hosted_text")
        self.assertTrue(decision.credential_authorization_required)
        self.assertIsNotNone(decision.provider_credential_binding_id_optional)
        self.assertFalse(decision.fallback_used)
        self.assertIn("plain_hosted_text_selected", decision.reason_codes)
        self.assertNotIn("platform:secret-alias/openrouter", str(decision))
        json.dumps(routing_decision_payload(decision))

    def test_effective_registry_uses_operator_activated_hosted_provider_from_store(self) -> None:
        store = self.make_provider_store()
        secret_store = self.make_secret_store()
        secret = create_platform_secret(
            secret_store,
            label="OpenRouter",
            raw_value="super-secret-token",
            alias="openrouter-routing",
            kind="api_key",
        )

        activation = activate_hosted_model_provider(
            store,
            secret_store=secret_store,
            workspace_id="default",
            provider_id="openrouter",
            secret_ref=build_secret_ref(alias=secret.alias or "openrouter-routing"),
        )
        decision = select_provider_for_profile(
            "fast_model",
            ProviderRoutingContext(
                workspace_id="default",
                provider_store=store,
                registry=effective_provider_registry(store),
                request_id="req-store-active",
            ),
        )

        self.assertEqual(activation.definition.status, "active")
        self.assertEqual(activation.routing_decision.selected_provider_id, "openrouter")
        self.assertEqual(decision.selected_provider_id, "openrouter")
        self.assertEqual(decision.execution_path, "plain_hosted_text")
        self.assertNotIn("super-secret-token", str(decision))

    def test_hosted_provider_activation_survives_json_store_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store_root = Path(temp_dir) / "providers"
            store = self.make_json_provider_store(store_root)
            secret_store = self.make_secret_store()
            secret = create_platform_secret(
                secret_store,
                label="OpenRouter",
                raw_value="super-secret-token",
                alias="openrouter-restart",
                kind="api_key",
            )

            activation = activate_hosted_model_provider(
                store,
                secret_store=secret_store,
                workspace_id="default",
                provider_id="openrouter",
                secret_ref=build_secret_ref(alias=secret.alias or "openrouter-restart"),
            )
            restarted_store = self.make_json_provider_store(store_root)
            decision = select_provider_for_profile(
                "fast_model",
                ProviderRoutingContext(
                    workspace_id="default",
                    provider_store=restarted_store,
                    registry=effective_provider_registry(restarted_store),
                    request_id="req-openrouter-restart",
                ),
            )

            self.assertEqual(activation.routing_decision.selected_provider_id, "openrouter")
            self.assertEqual(restarted_store.get_provider_definition("openrouter").status, "active")
            self.assertEqual(
                restarted_store.get_hosted_provider_selection(workspace_id="default", profile="fast_model").provider_id,
                "openrouter",
            )
            self.assertEqual(decision.selected_provider_id, "openrouter")
            self.assertEqual(decision.execution_path, "plain_hosted_text")
            self.assertNotIn("provider_disabled:openrouter", decision.reason_codes)
            self.assertNotIn("super-secret-token", str(decision))

    def test_fast_model_routes_to_selected_openrouter_model_after_activation(self) -> None:
        store = self.make_provider_store()
        secret_store = self.make_secret_store()
        secret = create_platform_secret(
            secret_store,
            label="OpenRouter",
            raw_value="super-secret-token",
            alias="openrouter-api-key",
            kind="api_key",
        )

        activation = activate_hosted_model_provider(
            store,
            secret_store=secret_store,
            workspace_id="default",
            provider_id="openrouter",
            secret_ref=build_secret_ref(alias=secret.alias or "openrouter-api-key"),
        )
        selection = configure_hosted_model_provider(
            store,
            workspace_id="default",
            provider_id="openrouter",
            model_id="nvidia/nemotron-3-ultra-550b-a55b:free",
        )
        decision = select_provider_for_profile(
            "fast_model",
            ProviderRoutingContext(
                workspace_id="default",
                provider_store=store,
                registry=effective_provider_registry(store),
                secret_store=secret_store,
                request_id="req-openrouter",
            ),
        )

        self.assertEqual(activation.hosted_selection.provider_id if activation.hosted_selection else None, "openrouter")
        self.assertEqual(selection.model_id, "nvidia/nemotron-3-ultra-550b-a55b:free")
        self.assertEqual(decision.selected_provider_id, "openrouter")
        self.assertEqual(decision.selected_model_id_or_voice_id, "nvidia/nemotron-3-ultra-550b-a55b:free")
        self.assertEqual(decision.selected_runtime_engine_id, None)
        self.assertEqual(decision.execution_path, "plain_hosted_text")
        self.assertIn("hosted_model_selection_present:openrouter", decision.reason_codes)
        self.assertNotIn("super-secret-token", str(decision))
        self.assertNotIn("platform:secret-alias/openrouter-api-key", str(decision))

    def test_fast_model_routes_to_selected_google_ai_studio_model_after_activation(self) -> None:
        store = self.make_provider_store()
        secret_store = self.make_secret_store()
        create_platform_secret(
            secret_store,
            label="Google AI Studio",
            raw_value="super-secret-token",
            alias="google-ai-studio-api-key",
            kind="api_key",
        )

        activation = activate_hosted_model_provider(
            store,
            secret_store=secret_store,
            workspace_id="default",
            provider_id="google-ai-studio",
            secret_ref=build_secret_ref(alias="google-ai-studio-api-key"),
        )
        selection = configure_hosted_model_provider(
            store,
            workspace_id="default",
            provider_id="google-ai-studio",
            model_id="gemini-3.1-flash-lite",
        )
        decision = select_provider_for_profile(
            "fast_model",
            ProviderRoutingContext(
                workspace_id="default",
                provider_store=store,
                registry=effective_provider_registry(store),
                secret_store=secret_store,
                request_id="req-google-ai-studio",
            ),
        )

        self.assertEqual(activation.hosted_selection.provider_id if activation.hosted_selection else None, "google-ai-studio")
        self.assertEqual(selection.model_id, "gemini-3.1-flash-lite")
        self.assertEqual(decision.selected_provider_id, "google-ai-studio")
        self.assertEqual(decision.selected_model_id_or_voice_id, "gemini-3.1-flash-lite")
        self.assertEqual(decision.execution_path, "plain_hosted_text")
        self.assertIn("hosted_model_selection_present:google-ai-studio", decision.reason_codes)
        self.assertNotIn("super-secret-token", str(decision))

    def test_fast_model_honors_session_hosted_model_override(self) -> None:
        store = self.make_provider_store()
        secret_store = self.make_secret_store()
        create_platform_secret(
            secret_store,
            label="OpenRouter",
            raw_value="super-secret-token",
            alias="openrouter-api-key",
            kind="api_key",
        )
        activate_hosted_model_provider(
            store,
            secret_store=secret_store,
            workspace_id="default",
            provider_id="openrouter",
            secret_ref=build_secret_ref(alias="openrouter-api-key"),
        )
        configure_hosted_model_provider(
            store,
            workspace_id="default",
            provider_id="openrouter",
            model_id="nvidia/nemotron-3-ultra-550b-a55b:free",
        )

        decision = select_provider_for_profile(
            "fast_model",
            ProviderRoutingContext(
                workspace_id="default",
                provider_store=store,
                registry=effective_provider_registry(store),
                secret_store=secret_store,
                request_id="req-openrouter-override",
                hosted_provider_id="openrouter",
                hosted_model_id="google/gemma-4-31b-it:free",
            ),
        )

        self.assertEqual(decision.selected_provider_id, "openrouter")
        self.assertEqual(decision.selected_model_id_or_voice_id, "google/gemma-4-31b-it:free")
        self.assertIn("hosted_provider_override_present:openrouter", decision.reason_codes)
        self.assertIn("hosted_model_override_present:google/gemma-4-31b-it:free", decision.reason_codes)

    def test_fast_model_invalid_session_model_override_fails_closed(self) -> None:
        store = self.make_provider_store()
        secret_store = self.make_secret_store()
        create_platform_secret(
            secret_store,
            label="OpenRouter",
            raw_value="super-secret-token",
            alias="openrouter-api-key",
            kind="api_key",
        )
        activate_hosted_model_provider(
            store,
            secret_store=secret_store,
            workspace_id="default",
            provider_id="openrouter",
            secret_ref=build_secret_ref(alias="openrouter-api-key"),
        )

        decision = select_provider_for_profile(
            "fast_model",
            ProviderRoutingContext(
                workspace_id="default",
                provider_store=store,
                registry=effective_provider_registry(store),
                secret_store=secret_store,
                request_id="req-openrouter-invalid-override",
                hosted_provider_id="openrouter",
                hosted_model_id="openrouter/not-real",
            ),
        )

        self.assertIsNone(decision.selected_provider_id)
        self.assertIsNone(decision.execution_path)
        self.assertIn("hosted_model_override_unavailable:openrouter", decision.reason_codes)

    def test_fast_model_speech_output_model_override_fails_closed(self) -> None:
        store = self.make_provider_store()
        secret_store = self.make_secret_store()
        create_platform_secret(
            secret_store,
            label="OpenRouter",
            raw_value="super-secret-token",
            alias="openrouter-api-key",
            kind="api_key",
        )
        activate_hosted_model_provider(
            store,
            secret_store=secret_store,
            workspace_id="default",
            provider_id="openrouter",
            secret_ref=build_secret_ref(alias="openrouter-api-key"),
        )

        decision = select_provider_for_profile(
            "fast_model",
            ProviderRoutingContext(
                workspace_id="default",
                provider_store=store,
                registry=effective_provider_registry(store),
                secret_store=secret_store,
                request_id="req-openrouter-speech-override",
                hosted_provider_id="openrouter",
                hosted_model_id="hexgrad/kokoro-82m",
            ),
        )

        self.assertIsNone(decision.selected_provider_id)
        self.assertIsNone(decision.execution_path)
        self.assertIn("hosted_model_output_unsupported:hexgrad/kokoro-82m", decision.reason_codes)

    def test_hosted_selection_preserves_openrouter_routing_by_model(self) -> None:
        store = self.make_provider_store()
        secret_store = self.make_secret_store()
        create_platform_secret(
            secret_store,
            label="OpenRouter",
            raw_value="super-secret-token",
            alias="openrouter-api-key",
            kind="api_key",
        )
        activate_hosted_model_provider(
            store,
            secret_store=secret_store,
            workspace_id="default",
            provider_id="openrouter",
            secret_ref=build_secret_ref(alias="openrouter-api-key"),
        )

        configure_hosted_model_provider(
            store,
            workspace_id="default",
            provider_id="openrouter",
            model_id="google/gemma-4-31b-it:free",
            openrouter_provider_routing={
                "mode": "only",
                "provider_id": "google-ai-studio",
                "allow_fallbacks": False,
                "sort": "latency",
            },
        )
        selection = configure_hosted_model_provider(
            store,
            workspace_id="default",
            provider_id="openrouter",
            model_id="nvidia/nemotron-3-ultra-550b-a55b:free",
            openrouter_provider_routing={"mode": "prefer", "provider_id": "nvidia"},
        )

        self.assertEqual(
            selection.openrouter_provider_routing_by_model["google/gemma-4-31b-it:free"]["provider_id"],
            "google-ai-studio",
        )
        self.assertEqual(
            selection.openrouter_provider_routing_by_model["nvidia/nemotron-3-ultra-550b-a55b:free"]["provider_id"],
            "nvidia",
        )

    def test_fast_model_does_not_select_missing_core_secret_binding_when_store_available(self) -> None:
        store = self.make_provider_store()
        bind_provider_credential(
            store,
            provider_id="openrouter",
            workspace_id="default",
            secret_ref="platform:secret-alias/missing-openrouter",
        )

        decision = select_provider_for_profile(
            "fast_model",
            ProviderRoutingContext(
                workspace_id="default",
                provider_store=store,
                registry=self.active_fast_registry(),
                secret_store=self.make_secret_store(),
                request_id="req-missing-secret",
            ),
        )

        self.assertIsNone(decision.selected_provider_id)
        self.assertIsNone(decision.execution_path)
        self.assertIn("provider_credential_binding_secret_missing", decision.reason_codes)
        self.assertIn("fallback_no_credential_authorization", decision.reason_codes)
        self.assertNotIn("platform:secret-alias/missing-openrouter", str(decision))

    def test_disabled_builtin_provider_with_bound_secret_is_routable(self) -> None:
        store = self.make_provider_store()
        secret_store = self.make_secret_store()
        create_platform_secret(
            secret_store,
            label="Google AI Studio",
            raw_value="super-secret-token",
            alias="google_ai_studio_api_key",
            kind="api_key",
        )
        bind_provider_secret(
            secret_store,
            provider_id="google-ai-studio",
            workspace_id="default",
            logical_name="google_ai_studio_api_key",
            secret_ref=build_secret_ref(alias="google_ai_studio_api_key"),
        )

        decision = select_provider_for_profile(
            "fast_model",
            ProviderRoutingContext(
                workspace_id="default",
                provider_store=store,
                registry=builtin_provider_registry(),
                secret_store=secret_store,
                hosted_provider_id="google-ai-studio",
                hosted_model_id="gemini-3.5-flash",
            ),
        )

        self.assertEqual(decision.selected_provider_id, "google-ai-studio")
        self.assertEqual(decision.selected_model_id_or_voice_id, "gemini-3.5-flash")
        self.assertEqual(decision.execution_path, "plain_hosted_text")
        self.assertNotIn("provider_disabled:google-ai-studio", decision.reason_codes)
        self.assertIn("provider_secret_binding_present", decision.reason_codes)

if __name__ == "__main__":
    unittest.main()
