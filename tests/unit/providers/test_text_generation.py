"""Hosted text generation client tests."""

from __future__ import annotations

from dataclasses import replace
import unittest
from unittest.mock import patch

from core.providers.provider_credentials import bind_provider_credential
from core.providers.routing import ProviderRoutingContext, select_provider_for_profile
from core.providers.service import builtin_provider_registry
from core.providers.store import ProviderCollections, ProviderDocumentStore
from core.providers.text_generation import (
    FakeHostedTextTransport,
    GoogleAIStudioTextGenerationClient,
    HostedTextGenerationError,
    OpenAICompatibleHttpTransport,
    OpenAICompatibleTextGenerationClient,
    TextGenerationContentPart,
    TextGenerationMessage,
    TextGenerationRequest,
    execute_hosted_text_generation,
)
from core.secrets.service import build_secret_ref, create_platform_secret
from core.secrets.store import SecretCollections, SecretDocumentStore
from tests.support.collections import FakeCollection


class HostedTextGenerationTest(unittest.TestCase):
    def make_provider_store(self) -> ProviderDocumentStore:
        return ProviderDocumentStore(
            ProviderCollections(
                definitions=FakeCollection(),
                bindings=FakeCollection(),
                selections=FakeCollection(),
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
            key_loader=lambda: b"test-key-material-for-hosted-text",
        )

    def active_fast_registry(self):
        registry = builtin_provider_registry()
        openrouter = registry.get_provider_definition("openrouter")
        registry.register_provider_definition(replace(openrouter, status="active"))
        return registry

    def request(
        self,
        *,
        stream: bool = False,
        content: str = "Hello",
        workspace_id: str | None = None,
        workspace_root: str | None = None,
    ) -> TextGenerationRequest:
        return TextGenerationRequest(
            model_id="google/gemma-4-31b-it:free",
            messages=[TextGenerationMessage(role="user", content=content)],
            system_prompt="Answer briefly.",
            max_output_tokens=64,
            timeout_seconds=10,
            stream=stream,
            workspace_id=workspace_id,
            workspace_root=workspace_root,
        )

    def test_fake_transport_non_streaming_normalizes_response(self) -> None:
        transport = FakeHostedTextTransport(response_text="hello from hosted")
        client = OpenAICompatibleTextGenerationClient(
            provider_id="openrouter",
            api_key="secret-token",
            transport=transport,
        )

        result = client.generate(self.request())

        self.assertEqual(result.output_text, "hello from hosted")
        self.assertEqual(result.deltas, ["hello from hosted"])
        self.assertEqual(transport.requests[0]["headers"]["Authorization"], "<redacted>")
        self.assertNotIn("tools", transport.requests[0]["payload"])
        self.assertNotIn("secret-token", str(result))
        self.assertNotIn("secret-token", str(transport.requests))

    def test_openrouter_uses_openai_compatible_chat_completions_endpoint(self) -> None:
        transport = FakeHostedTextTransport(response_text="hello from openrouter")
        client = OpenAICompatibleTextGenerationClient(
            provider_id="openrouter",
            api_key="secret-token",
            transport=transport,
        )

        result = client.generate(
            TextGenerationRequest(
                model_id="google/gemma-4-31b-it:free",
                messages=[TextGenerationMessage(role="user", content="Hello")],
            )
        )

        self.assertEqual(result.output_text, "hello from openrouter")
        self.assertEqual(transport.requests[0]["endpoint_url"], "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(transport.requests[0]["payload"]["model"], "google/gemma-4-31b-it:free")
        self.assertNotIn("secret-token", str(transport.requests))

    def test_openrouter_serializes_multimodal_image_content_parts(self) -> None:
        transport = FakeHostedTextTransport(response_text="image answer")
        client = OpenAICompatibleTextGenerationClient(
            provider_id="openrouter",
            api_key="secret-token",
            transport=transport,
        )

        result = client.generate(
            TextGenerationRequest(
                model_id="google/gemma-4-31b-it:free",
                messages=[
                    TextGenerationMessage(
                        role="user",
                        content=[
                            TextGenerationContentPart(type="text", text="Describe this image."),
                            TextGenerationContentPart(type="image_url", image_url="data:image/png;base64,aGVsbG8="),
                        ],
                    )
                ],
            )
        )

        message = transport.requests[0]["payload"]["messages"][0]
        self.assertEqual(result.output_text, "image answer")
        self.assertEqual(message["content"][0], {"type": "text", "text": "Describe this image."})
        self.assertEqual(message["content"][1], {"type": "image_url", "image_url": {"url": "data:image/png;base64,aGVsbG8="}})

    def test_openrouter_serializes_hosted_attachment_content_parts(self) -> None:
        transport = FakeHostedTextTransport(response_text="attachment answer")
        client = OpenAICompatibleTextGenerationClient(
            provider_id="openrouter",
            api_key="secret-token",
            transport=transport,
        )

        client.generate(
            TextGenerationRequest(
                model_id="google/gemma-4-31b-it:free",
                messages=[
                    TextGenerationMessage(
                        role="user",
                        content=[
                            TextGenerationContentPart(type="text", text="Inspect these attachments."),
                            TextGenerationContentPart(type="inline_data", mime_type="audio/wav", data="YXVkaW8=", filename="recording.wav"),
                            TextGenerationContentPart(type="inline_data", mime_type="video/mp4", data="dmlkZW8=", filename="clip.mp4"),
                            TextGenerationContentPart(type="inline_data", mime_type="application/pdf", data="cGRm", filename="document.pdf"),
                        ],
                    )
                ],
            )
        )

        content = transport.requests[0]["payload"]["messages"][0]["content"]
        self.assertEqual(content[1], {"type": "input_audio", "input_audio": {"data": "YXVkaW8=", "format": "wav"}})
        self.assertEqual(content[2], {"type": "video_url", "video_url": {"url": "data:video/mp4;base64,dmlkZW8="}})
        self.assertEqual(
            content[3],
            {
                "type": "file",
                "file": {
                    "filename": "document.pdf",
                    "file_data": "data:application/pdf;base64,cGRm",
                },
            },
        )

    def test_openrouter_serializes_provider_routing_preferences(self) -> None:
        transport = FakeHostedTextTransport(response_text="routed")
        client = OpenAICompatibleTextGenerationClient(
            provider_id="openrouter",
            api_key="secret-token",
            transport=transport,
        )

        client.generate(
            TextGenerationRequest(
                model_id="google/gemma-4-31b-it:free",
                messages=[TextGenerationMessage(role="user", content="Hello")],
                provider_routing={
                    "mode": "only",
                    "provider_id": "google-ai-studio",
                    "allow_fallbacks": False,
                    "require_parameters": True,
                    "sort": "latency",
                    "data_collection": "deny", "zdr": True,
                    "quantizations": ["bf16"],
                },
            )
        )

        self.assertEqual(
            transport.requests[0]["payload"]["provider"],
            {
                "only": ["google-ai-studio"],
                "allow_fallbacks": False,
                "require_parameters": True,
                "sort": "latency",
                "data_collection": "deny", "zdr": True,
                "quantizations": ["bf16"],
            },
        )

    def test_google_ai_studio_serializes_gemini_generate_content_request(self) -> None:
        transport = FakeHostedTextTransport(
            payload={
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": "hello from gemini"}],
                        }
                    }
                ]
            }
        )
        client = GoogleAIStudioTextGenerationClient(api_key="secret-token", transport=transport)

        result = client.generate(
            TextGenerationRequest(
                model_id="gemini-3.5-flash",
                messages=[
                    TextGenerationMessage(
                        role="user",
                        content=[
                            TextGenerationContentPart(type="text", text="Describe this image."),
                            TextGenerationContentPart(type="image_url", image_url="data:image/png;base64,aGVsbG8="),
                        ],
                    )
                ],
                system_prompt="Answer briefly.",
                max_output_tokens=64,
            )
        )

        request = transport.requests[0]
        self.assertEqual(
            request["endpoint_url"],
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent",
        )
        self.assertEqual(request["headers"]["x-goog-api-key"], "<redacted>")
        self.assertEqual(result.output_text, "hello from gemini")
        self.assertEqual(request["payload"]["systemInstruction"], {"parts": [{"text": "Answer briefly."}]})
        self.assertEqual(request["payload"]["generationConfig"], {"maxOutputTokens": 64})
        self.assertEqual(request["payload"]["contents"][0]["role"], "user")
        self.assertEqual(request["payload"]["contents"][0]["parts"][0], {"text": "Describe this image."})
        self.assertEqual(
            request["payload"]["contents"][0]["parts"][1],
            {"inlineData": {"mimeType": "image/png", "data": "aGVsbG8="}},
        )
        self.assertNotIn("secret-token", str(transport.requests))

    def test_google_ai_studio_serializes_inline_attachment_content_parts(self) -> None:
        transport = FakeHostedTextTransport(
            payload={
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": "audio answer"}],
                        }
                    }
                ]
            }
        )
        client = GoogleAIStudioTextGenerationClient(api_key="secret-token", transport=transport)

        client.generate(
            TextGenerationRequest(
                model_id="gemini-3.5-flash",
                messages=[
                    TextGenerationMessage(
                        role="user",
                        content=[
                            TextGenerationContentPart(type="text", text="Transcribe this."),
                            TextGenerationContentPart(type="inline_data", mime_type="audio/wav", data="YXVkaW8=", filename="recording.wav"),
                        ],
                    )
                ],
            )
        )

        parts = transport.requests[0]["payload"]["contents"][0]["parts"]
        self.assertEqual(parts[1], {"inlineData": {"mimeType": "audio/wav", "data": "YXVkaW8="}})

    def test_google_ai_studio_serializes_assistant_history_as_model_role(self) -> None:
        transport = FakeHostedTextTransport(
            payload={
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": "follow up"}],
                        }
                    }
                ]
            }
        )
        client = GoogleAIStudioTextGenerationClient(api_key="secret-token", transport=transport)

        client.generate(
            TextGenerationRequest(
                model_id="gemini-3.5-flash",
                messages=[
                    TextGenerationMessage(role="user", content="Question one"),
                    TextGenerationMessage(role="assistant", content="Answer one"),
                    TextGenerationMessage(role="user", content="Question two"),
                ],
            )
        )

        self.assertEqual([item["role"] for item in transport.requests[0]["payload"]["contents"]], ["user", "model", "user"])

    def test_blocked_operational_reference_in_history_fails_closed(self) -> None:
        client = OpenAICompatibleTextGenerationClient(
            provider_id="openrouter",
            api_key="secret-token",
            transport=FakeHostedTextTransport(response_text="unused"),
        )

        with self.assertRaises(HostedTextGenerationError) as raised:
            client.generate(
                TextGenerationRequest(
                    model_id="google/gemma-4-31b-it:free",
                    messages=[
                        TextGenerationMessage(role="user", content="Earlier path /home/ubuntu/projects/maverick-v3/workspaces/default/data"),
                        TextGenerationMessage(role="assistant", content="Acknowledged."),
                        TextGenerationMessage(role="user", content="Now answer normally."),
                    ],
                    workspace_root="/home/ubuntu/projects/maverick-v3/workspaces/default",
                    workspace_id="default",
                )
            )

        self.assertEqual(raised.exception.reason_code, "hosted_text_request_contains_operational_reference")

    def test_fake_transport_streaming_normalizes_deltas(self) -> None:
        transport = FakeHostedTextTransport(chunks=["hel", "lo"])
        client = OpenAICompatibleTextGenerationClient(
            provider_id="openrouter",
            api_key="secret-token",
            transport=transport,
        )
        live_deltas: list[str] = []

        result = client.generate(self.request(stream=True), delta_sink=live_deltas.append)

        self.assertEqual(result.output_text, "hello")
        self.assertEqual(result.deltas, ["hel", "lo"])
        self.assertEqual(live_deltas, ["hel", "lo"])

    def test_openai_streaming_transport_emits_live_chunks(self) -> None:
        class StreamingResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

            def __iter__(self):
                yield b'data: {"choices":[{"delta":{"content":"hel"}}]}\n'
                yield b'data: {"choices":[{"delta":{"content":"lo"}}]}\n'
                yield b"data: [DONE]\n"

        client = OpenAICompatibleTextGenerationClient(
            provider_id="openrouter",
            api_key="secret-token",
            transport=OpenAICompatibleHttpTransport(),
        )
        live_deltas: list[str] = []

        with patch("core.providers.text_generation.urllib_request.urlopen", return_value=StreamingResponse()):
            result = client.generate(self.request(stream=True), delta_sink=live_deltas.append)

        self.assertEqual(result.output_text, "hello")
        self.assertEqual(result.deltas, ["hel", "lo"])
        self.assertEqual(live_deltas, ["hel", "lo"])

    def test_provider_errors_map_to_reason_codes(self) -> None:
        cases = [
            (FakeHostedTextTransport(timed_out=True), "provider_timeout"),
            (FakeHostedTextTransport(status_code=401), "provider_credential_rejected"),
            (FakeHostedTextTransport(status_code=429), "provider_rate_limited"),
            (FakeHostedTextTransport(status_code=500), "provider_http_error"),
            (FakeHostedTextTransport(payload={"unexpected": []}), "provider_response_invalid"),
        ]
        for transport, reason_code in cases:
            with self.subTest(reason_code=reason_code):
                client = OpenAICompatibleTextGenerationClient(
                    provider_id="openrouter",
                    api_key="secret-token",
                    transport=transport,
                )
                with self.assertRaises(HostedTextGenerationError) as raised:
                    client.generate(self.request())
                self.assertEqual(raised.exception.reason_code, reason_code)
                self.assertNotIn("secret-token", str(raised.exception))

    def test_http_transport_malformed_200_maps_to_provider_response_invalid(self) -> None:
        class MalformedResponse:
            status = 200

            def __init__(self, payload: bytes) -> None:
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

            def read(self) -> bytes:
                return self.payload

        cases = [b"{not-json", b"\xff"]
        for payload in cases:
            with self.subTest(payload=payload):
                client = OpenAICompatibleTextGenerationClient(
                    provider_id="openrouter",
                    api_key="secret-token",
                    transport=OpenAICompatibleHttpTransport(),
                )
                with (
                    patch("core.providers.text_generation.urllib_request.urlopen", return_value=MalformedResponse(payload)),
                    self.assertRaises(HostedTextGenerationError) as raised,
                ):
                    client.generate(self.request())
                self.assertEqual(raised.exception.reason_code, "provider_response_invalid")
                self.assertNotIn("secret-token", str(raised.exception))

    def test_http_transport_malformed_stream_maps_to_provider_response_invalid(self) -> None:
        class MalformedStreamResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

            def __iter__(self):
                yield b"\xff\n"

        client = OpenAICompatibleTextGenerationClient(
            provider_id="openrouter",
            api_key="secret-token",
            transport=OpenAICompatibleHttpTransport(),
        )

        with (
            patch("core.providers.text_generation.urllib_request.urlopen", return_value=MalformedStreamResponse()),
            self.assertRaises(HostedTextGenerationError) as raised,
        ):
            client.generate(self.request(stream=True))

        self.assertEqual(raised.exception.reason_code, "provider_response_invalid")
        self.assertNotIn("secret-token", str(raised.exception))

    def test_hosted_text_request_rejects_operational_references(self) -> None:
        client = OpenAICompatibleTextGenerationClient(
            provider_id="openrouter",
            api_key="secret-token",
            transport=FakeHostedTextTransport(),
        )

        cases = [
            self.request(content="Local path: /tmp/file.txt"),
            self.request(content="Referenced app-owned records:\n- record-1"),
            self.request(
                content="See /tmp/maverick/workspaces/acme/data/mail/message.json",
                workspace_id="acme",
                workspace_root="/tmp/maverick/workspaces/acme",
            ),
            self.request(
                content="See workspaces/acme/data/mail/message.json",
                workspace_id="acme",
                workspace_root="/tmp/maverick/workspaces/acme",
            ),
        ]

        for request in cases:
            with self.subTest(content=request.messages[0].content), self.assertRaises(HostedTextGenerationError) as raised:
                client.generate(request)
            self.assertEqual(raised.exception.reason_code, "hosted_text_request_contains_operational_reference")

    def test_executor_resolves_provider_binding_inside_controlled_path(self) -> None:
        provider_store = self.make_provider_store()
        secret_store = self.make_secret_store()
        secret = create_platform_secret(
            secret_store,
            label="OpenRouter",
            raw_value="super-secret-token",
            alias="openrouter-hosted-text",
            kind="api_key",
        )
        bind_provider_credential(
            provider_store,
            provider_id="openrouter",
            workspace_id="default",
            secret_ref=build_secret_ref(secret_id=secret.secret_id),
        )
        decision = select_provider_for_profile(
            "fast_model",
            ProviderRoutingContext(
                workspace_id="default",
                provider_store=provider_store,
                registry=self.active_fast_registry(),
                request_id="req-hosted",
            ),
        )
        transport = FakeHostedTextTransport(response_text="resolved secret worked")

        result = execute_hosted_text_generation(
            provider_store,
            secret_store,
            decision=decision,
            request=self.request(),
            runtime_session_id="sess-1",
            transport=transport,
        )

        self.assertEqual(result.output_text, "resolved secret worked")
        self.assertNotIn("super-secret-token", str(result))
        self.assertNotIn("super-secret-token", str(transport.requests))


if __name__ == "__main__":
    unittest.main()
