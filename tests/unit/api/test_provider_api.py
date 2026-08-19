"""Provider API read-only surface tests."""

from __future__ import annotations

from io import BytesIO
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.api.provider_api import _agentic_model_reasoning, handle_provider_api
from core.api.session_api import RequestSession
from core.providers.provider_credentials import bind_provider_credential, disable_provider_binding
from core.providers.service import builtin_provider_registry, register_builtin_providers
from core.providers.store import ProviderCollections, ProviderDocumentStore
from core.runtime.service import create_runtime_session
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.secrets.service import bind_provider_secret, build_secret_ref, create_platform_secret
from core.secrets.store import SecretCollections, SecretDocumentStore
from tests.support.collections import FakeCollection


class ProviderApiTest(unittest.TestCase):
    def test_agentic_codex_profile_exposes_provider_reasoning_choices(self) -> None:
        default, options = _agentic_model_reasoning(
            builtin_provider_registry(refresh_model_catalog=False),
            SimpleNamespace(
                model_provider_id="codex",
                runtime_engine_id="codex",
                model_id="gpt-5.6-sol",
            ),
        )

        self.assertIn(default, {item["effort"] for item in options})
        self.assertIn("xhigh", {item["effort"] for item in options})

    def make_provider_store(self) -> ProviderDocumentStore:
        store = ProviderDocumentStore(
            ProviderCollections(
                definitions=FakeCollection(),
                bindings=FakeCollection(),
                selections=FakeCollection(),
            )
        )
        register_builtin_providers(store)
        return store

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

    def make_runtime_store(self) -> RuntimeDocumentStore:
        return RuntimeDocumentStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
            )
        )

    def make_state(self):
        return SimpleNamespace(
            provider_store=self.make_provider_store(),
            secret_store=self.make_secret_store(),
            runtime_store=self.make_runtime_store(),
            workspace_store=SimpleNamespace(),
            observability_store=None,
        )

    def test_provider_list_exposes_role_and_capabilities(self) -> None:
        status, payload = self.invoke("/api/providers")

        self.assertEqual(status, "200 OK")
        self.assertEqual(payload["items"][0]["provider_id"], "codex")
        self.assertEqual(payload["items"][0]["provider_role"], "runtime_engine")
        self.assertIn("capabilities", payload["items"][0])
        self.assertNotIn("secret_ref", str(payload))

    def test_provider_route_returns_redaction_safe_decision(self) -> None:
        status, payload = self.invoke("/api/providers/route", query="profile=fast_model&request_id=req-api")

        self.assertEqual(status, "200 OK")
        decision = payload["decision"]
        self.assertEqual(decision["request_id"], "req-api")
        self.assertEqual(decision["candidate_provider_ids"], ["google-ai-studio", "openrouter"])
        self.assertIn("provider_disabled:google-ai-studio", decision["reason_codes"])
        self.assertIn("provider_disabled:openrouter", decision["reason_codes"])
        self.assertNotIn("secret_ref", str(payload))

    def test_operator_can_activate_hosted_provider_and_route_preview_uses_it(self) -> None:
        state = self.make_state()
        secret = create_platform_secret(
            state.secret_store,
            label="Google AI Studio API",
            raw_value="super-secret-token",
            alias="google-ai-studio-api",
            kind="api_key",
        )

        status, payload = self.invoke(
            "/api/providers/hosted/active",
            method="POST",
            body={
                "provider_id": "google-ai-studio",
                "secret_ref": build_secret_ref(alias=secret.alias or "google-ai-studio-api"),
            },
            state=state,
        )
        route_status, route_payload = self.invoke(
            "/api/providers/route",
            query="profile=fast_model&request_id=req-api-active",
            state=state,
        )

        self.assertEqual(status, "200 OK")
        self.assertEqual(payload["provider"]["provider_id"], "google-ai-studio")
        self.assertEqual(payload["provider"]["status"], "active")
        self.assertEqual(payload["credential_binding"]["provider_id"], "google-ai-studio")
        self.assertEqual(payload["preflight"]["selected_provider_id"], "google-ai-studio")
        self.assertEqual(route_status, "200 OK")
        self.assertEqual(route_payload["decision"]["selected_provider_id"], "google-ai-studio")
        self.assertNotIn("super-secret-token", json.dumps(payload))
        self.assertNotIn("secret_ref", json.dumps(payload))

    def test_operator_can_activate_openrouter_and_save_hosted_model(self) -> None:
        state = self.make_state()
        secret = create_platform_secret(
            state.secret_store,
            label="OpenRouter API",
            raw_value="super-secret-token",
            alias="openrouter_api_key",
            kind="api_key",
        )

        status, payload = self.invoke(
            "/api/providers/hosted/active",
            method="POST",
            body={
                "provider_id": "openrouter",
                "secret_ref": build_secret_ref(alias=secret.alias or "openrouter_api_key"),
                "label": "OpenRouter hosted text",
            },
            state=state,
        )
        with patch("core.api.provider_api.require_provider_selection_authority", return_value=None):
            save_status, save_payload = self.invoke(
                "/api/providers/hosted/selection",
                method="POST",
                body={
                    "provider_id": "openrouter",
                    "model_id": "nvidia/nemotron-3-ultra-550b-a55b:free",
                },
                state=state,
            )
        route_status, route_payload = self.invoke(
            "/api/providers/route",
            query="profile=fast_model&request_id=req-openrouter-api",
            state=state,
        )

        self.assertEqual(status, "200 OK")
        self.assertEqual(payload["provider"]["provider_id"], "openrouter")
        self.assertEqual(payload["hosted_selection"]["provider_id"], "openrouter")
        self.assertEqual(payload["hosted_selection"]["model_id"], "google/gemma-4-31b-it:free")
        self.assertEqual(payload["preflight"]["selected_provider_id"], "openrouter")
        self.assertEqual(save_status, "200 OK")
        self.assertIsNone(save_payload["active_provider"])
        self.assertEqual(save_payload["hosted_text"]["active_provider"]["provider_id"], "openrouter")
        self.assertEqual(
            save_payload["hosted_text"]["model_settings"]["selected_model_id"],
            "nvidia/nemotron-3-ultra-550b-a55b:free",
        )
        self.assertEqual(route_status, "200 OK")
        self.assertEqual(route_payload["decision"]["selected_provider_id"], "openrouter")
        self.assertEqual(route_payload["decision"]["selected_model_id_or_voice_id"], "nvidia/nemotron-3-ultra-550b-a55b:free")
        self.assertIsNone(route_payload["decision"]["selected_runtime_engine_id"])
        self.assertNotIn("super-secret-token", json.dumps(payload))
        self.assertNotIn("super-secret-token", json.dumps(save_payload))
        self.assertNotIn("platform:secret-alias/openrouter_api_key", json.dumps(payload))
        self.assertNotIn("secret_ref", json.dumps(save_payload))

    def test_saving_openrouter_speech_model_routing_does_not_replace_fast_model(self) -> None:
        state = self.make_state()
        secret = create_platform_secret(
            state.secret_store,
            label="OpenRouter API",
            raw_value="super-secret-token",
            alias="openrouter_api_key",
            kind="api_key",
        )

        status, payload = self.invoke(
            "/api/providers/hosted/active",
            method="POST",
            body={
                "provider_id": "openrouter",
                "secret_ref": build_secret_ref(alias=secret.alias or "openrouter_api_key"),
                "label": "OpenRouter hosted text",
            },
            state=state,
        )
        with patch("core.api.provider_api.require_provider_selection_authority", return_value=None):
            save_status, save_payload = self.invoke(
                "/api/providers/hosted/selection",
                method="POST",
                body={
                    "provider_id": "openrouter",
                    "model_id": "hexgrad/kokoro-82m",
                    "openrouter_provider_routing": {
                        "mode": "only",
                        "provider_id": "deepinfra",
                        "allow_fallbacks": False,
                        "zdr": True,
                    },
                },
                state=state,
            )
        route_status, route_payload = self.invoke(
            "/api/providers/route",
            query="profile=fast_model&request_id=req-openrouter-kokoro-api",
            state=state,
        )

        self.assertEqual(status, "200 OK")
        self.assertEqual(payload["hosted_selection"]["model_id"], "google/gemma-4-31b-it:free")
        self.assertEqual(save_status, "200 OK")
        self.assertEqual(save_payload["hosted_text"]["active_provider"]["provider_id"], "openrouter")
        self.assertEqual(
            save_payload["hosted_text"]["selection"]["model_id"],
            "google/gemma-4-31b-it:free",
        )
        self.assertEqual(
            save_payload["hosted_text"]["selection"]["openrouter_provider_routing_by_model"]["hexgrad/kokoro-82m"][
                "provider_id"
            ],
            "deepinfra",
        )
        self.assertTrue(
            save_payload["hosted_text"]["selection"]["openrouter_provider_routing_by_model"]["hexgrad/kokoro-82m"][
                "zdr"
            ]
        )
        self.assertEqual(
            save_payload["hosted_text"]["model_settings"]["selected_model_id"],
            "google/gemma-4-31b-it:free",
        )
        self.assertEqual(route_status, "200 OK")
        self.assertEqual(route_payload["decision"]["selected_provider_id"], "openrouter")
        self.assertEqual(route_payload["decision"]["selected_model_id_or_voice_id"], "google/gemma-4-31b-it:free")

    def test_operator_can_activate_deepgram_speech_provider(self) -> None:
        state = self.make_state()
        secret = create_platform_secret(
            state.secret_store,
            label="Deepgram API",
            raw_value="super-secret-token",
            alias="deepgram_api_key",
            kind="api_key",
        )

        status, payload = self.invoke(
            "/api/providers/speech/active",
            method="POST",
            body={
                "provider_id": "deepgram",
                "secret_ref": build_secret_ref(alias=secret.alias or "deepgram_api_key"),
                "label": "Deepgram speech-to-text",
            },
            state=state,
        )
        provider_status, provider_payload = self.invoke("/api/providers/active", state=state)

        self.assertEqual(status, "200 OK")
        self.assertEqual(payload["provider"]["provider_id"], "deepgram")
        self.assertEqual(payload["provider"]["status"], "active")
        self.assertEqual(payload["credential_binding"]["provider_id"], "deepgram")
        self.assertEqual(payload["speech_selection"]["audio_transcription_model_id"], "nova-3")
        self.assertEqual(payload["speech_selection"]["conversation_model_id"], "flux-general-multi")
        self.assertEqual(payload["speech_stt"]["active_provider"]["provider_id"], "deepgram")
        self.assertEqual(payload["speech_stt"]["model_settings"]["audio_transcription_model_id"], "nova-3")
        self.assertEqual(payload["speech_stt"]["model_settings"]["conversation_model_id"], "flux-general-multi")
        self.assertEqual(provider_status, "200 OK")
        self.assertEqual(provider_payload["speech_stt"]["active_provider"]["provider_id"], "deepgram")
        self.assertEqual(
            [item["model_id"] for item in provider_payload["speech_stt"]["model_settings"]["available_audio_transcription_models"]],
            ["nova-3", "nova-3-general", "nova-3-medical"],
        )
        self.assertEqual(
            [item["model_id"] for item in provider_payload["speech_stt"]["model_settings"]["available_conversation_models"]],
            ["flux-general-multi", "flux-general-en"],
        )
        self.assertNotIn("super-secret-token", json.dumps(payload))
        self.assertNotIn("secret_ref", json.dumps(payload))

    def test_admin_can_configure_deepgram_speech_models_by_purpose(self) -> None:
        state = self.make_state()
        secret = create_platform_secret(
            state.secret_store,
            label="Deepgram API",
            raw_value="super-secret-token",
            alias="deepgram_api_key",
            kind="api_key",
        )
        self.invoke(
            "/api/providers/speech/active",
            method="POST",
            body={
                "provider_id": "deepgram",
                "secret_ref": build_secret_ref(alias=secret.alias or "deepgram_api_key"),
            },
            state=state,
        )

        with patch("core.api.provider_api.require_provider_selection_authority", return_value=None):
            status, payload = self.invoke(
                "/api/providers/speech/selection",
                method="POST",
                body={
                    "provider_id": "deepgram",
                    "audio_transcription_model_id": "nova-3-general",
                    "conversation_model_id": "flux-general-en",
                },
                state=state,
            )

        self.assertEqual(status, "200 OK")
        speech = payload["speech_stt"]
        self.assertEqual(speech["selection"]["audio_transcription_model_id"], "nova-3-general")
        self.assertEqual(speech["selection"]["conversation_model_id"], "flux-general-en")
        self.assertEqual(speech["model_settings"]["audio_transcription_model_id"], "nova-3-general")
        self.assertEqual(speech["model_settings"]["conversation_model_id"], "flux-general-en")
        self.assertEqual(
            speech["model_settings"]["endpoints"]["audio_transcription"],
            "https://api.deepgram.com/v1/listen?model=nova-3-general",
        )
        self.assertEqual(
            speech["model_settings"]["endpoints"]["conversation"],
            "wss://api.deepgram.com/v2/listen?model=flux-general-en",
        )

    def test_hosted_text_status_only_marks_routable_provider_active(self) -> None:
        state = self.make_state()
        secret = create_platform_secret(
            state.secret_store,
            label="OpenRouter API",
            raw_value="super-secret-token",
            alias="openrouter_api_key",
            kind="api_key",
        )
        status, payload = self.invoke(
            "/api/providers/hosted/active",
            method="POST",
            body={
                "provider_id": "openrouter",
                "secret_ref": build_secret_ref(alias=secret.alias or "openrouter_api_key"),
                "label": "OpenRouter hosted text",
            },
            state=state,
        )
        disable_provider_binding(state.provider_store, payload["credential_binding"]["binding_id"])

        status_after_disable, payload_after_disable = self.invoke(
            "/api/providers/active",
            state=state,
        )

        self.assertEqual(status, "200 OK")
        self.assertEqual(status_after_disable, "200 OK")
        hosted_text = payload_after_disable["hosted_text"]
        self.assertIsNone(hosted_text["active_provider"])
        self.assertIsNone(hosted_text["model_settings"])
        self.assertEqual(hosted_text["selection"]["provider_id"], "openrouter")
        self.assertIsNone(hosted_text["route_preview"]["selected_provider_id"])
        self.assertIn("provider_credential_binding_missing", hosted_text["route_preview"]["reason_codes"])
        self.assertNotIn("super-secret-token", json.dumps(payload_after_disable))
        self.assertNotIn("secret_ref", json.dumps(payload_after_disable))

    def test_hosted_text_status_marks_bound_google_provider_active(self) -> None:
        state = self.make_state()
        secret = create_platform_secret(
            state.secret_store,
            label="Google AI Studio API",
            raw_value="super-secret-token",
            alias="google_ai_studio_api_key",
            kind="api_key",
        )
        bind_provider_secret(
            state.secret_store,
            provider_id="google-ai-studio",
            workspace_id="default",
            logical_name="google_ai_studio_api_key",
            secret_ref=build_secret_ref(alias=secret.alias or "google_ai_studio_api_key"),
        )

        status, payload = self.invoke("/api/providers/active", state=state)

        self.assertEqual(status, "200 OK")
        google = next(
            provider
            for provider in payload["hosted_text"]["available_providers"]
            if provider["provider_id"] == "google-ai-studio"
        )
        self.assertEqual(google["status"], "active")
        self.assertEqual(payload["hosted_text"]["route_preview"]["selected_provider_id"], "google-ai-studio")
        self.assertNotIn("super-secret-token", json.dumps(payload))
        self.assertNotIn("secret_ref", json.dumps(payload))

    def test_hosted_activation_rejects_caller_supplied_binding_id_collision(self) -> None:
        state = self.make_state()
        secret = create_platform_secret(
            state.secret_store,
            label="Shared API",
            raw_value="super-secret-token",
            alias="shared-api",
            kind="api_key",
        )
        existing = bind_provider_credential(
            state.provider_store,
            provider_id="google-ai-studio",
            workspace_id="default",
            secret_ref=build_secret_ref(alias=secret.alias or "shared-api"),
            binding_id="shared-binding",
        )

        status, payload = self.invoke(
            "/api/providers/hosted/active",
            method="POST",
            body={
                "provider_id": "google-ai-studio",
                "secret_ref": build_secret_ref(alias=secret.alias or "shared-api"),
                "binding_id": existing.binding_id,
            },
            state=state,
        )

        self.assertEqual(status, "400 Bad Request")
        self.assertEqual(payload["error"], "binding_id_not_supported")
        self.assertEqual(state.provider_store.get_provider_binding(existing.binding_id).provider_id, "google-ai-studio")

    def test_runtime_status_exposes_runtime_mode(self) -> None:
        state = self.make_state()
        create_runtime_session(
            state.runtime_store,
            session_id="sess-plain",
            workspace_id="default",
            agent_id="chat",
            runtime_mode="plain_hosted_chat",
        )

        status, payload = self.invoke("/api/runtime/status", state=state)
        self.assertEqual(status, "200 OK")
        self.assertEqual(payload["sessions"][0]["runtime_mode"], "plain_hosted_chat")

    def invoke(
        self,
        path: str,
        *,
        query: str = "",
        method: str = "GET",
        body: dict | None = None,
        state=None,
    ) -> tuple[str, dict]:
        state = state or self.make_state()
        context = RequestSession(
            user=SimpleNamespace(user_id="user-1", platform_role="admin"),
            session=SimpleNamespace(session_id="session-1"),
            workspace_id="default",
        )
        body_bytes = json.dumps(body or {}).encode("utf-8") if body is not None else b""
        environ = {
            "PATH_INFO": path,
            "QUERY_STRING": query,
            "REQUEST_METHOD": method,
            "wsgi.input": BytesIO(body_bytes),
            "CONTENT_LENGTH": str(len(body_bytes)),
            "CONTENT_TYPE": "application/json",
        }
        captured: dict[str, object] = {}
        def start_response(status: str, headers: list[tuple[str, str]]) -> None:
            captured["status"] = status
            captured["headers"] = headers

        with patch("core.api.provider_api.require_session", return_value=context):
            body = handle_provider_api(state, environ, start_response)
        assert body is not None
        return str(captured["status"]), json.loads(b"".join(body).decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
