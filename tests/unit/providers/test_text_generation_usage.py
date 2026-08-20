"""Provider-reported hosted text token usage tests."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from core.providers.text_generation import (
    FakeHostedTextTransport,
    GoogleAIStudioTextGenerationClient,
    OpenAICompatibleHttpTransport,
    OpenAICompatibleTextGenerationClient,
    TextGenerationMessage,
    TextGenerationRequest,
)


def _request(*, stream: bool = False) -> TextGenerationRequest:
    return TextGenerationRequest(
        model_id="google/gemma-4-31b-it:free",
        messages=[TextGenerationMessage(role="user", content="Hello")],
        stream=stream,
    )


class HostedTextGenerationUsageTest(unittest.TestCase):
    def test_openai_compatible_response_exposes_exact_token_usage(self) -> None:
        transport = FakeHostedTextTransport(
            payload={
                "choices": [{"message": {"content": "usage answer"}}],
                "usage": {
                    "prompt_tokens": 120,
                    "completion_tokens": 30,
                    "total_tokens": 150,
                    "prompt_tokens_details": {"cached_tokens": 20},
                    "completion_tokens_details": {"reasoning_tokens": 10},
                },
            }
        )
        client = OpenAICompatibleTextGenerationClient(
            provider_id="openrouter",
            api_key="secret-token",
            transport=transport,
        )

        result = client.generate(_request())

        self.assertIsNotNone(result.usage)
        assert result.usage is not None
        self.assertEqual(result.usage.input_tokens, 120)
        self.assertEqual(result.usage.cached_input_tokens, 20)
        self.assertEqual(result.usage.output_tokens, 30)
        self.assertEqual(result.usage.reasoning_output_tokens, 10)
        self.assertEqual(result.usage.total_tokens, 150)

    def test_google_ai_studio_response_exposes_token_usage(self) -> None:
        transport = FakeHostedTextTransport(
            payload={
                "candidates": [{"content": {"parts": [{"text": "usage answer"}]}}],
                "usageMetadata": {
                    "promptTokenCount": 80,
                    "cachedContentTokenCount": 10,
                    "candidatesTokenCount": 20,
                    "thoughtsTokenCount": 5,
                    "totalTokenCount": 100,
                },
            }
        )
        client = GoogleAIStudioTextGenerationClient(api_key="secret-token", transport=transport)

        result = client.generate(
            TextGenerationRequest(
                model_id="gemini-3.5-flash",
                messages=[TextGenerationMessage(role="user", content="Hello")],
            )
        )

        self.assertIsNotNone(result.usage)
        assert result.usage is not None
        self.assertEqual(result.usage.input_tokens, 80)
        self.assertEqual(result.usage.cached_input_tokens, 10)
        self.assertEqual(result.usage.output_tokens, 20)
        self.assertEqual(result.usage.reasoning_output_tokens, 5)
        self.assertEqual(result.usage.total_tokens, 100)

    def test_openai_streaming_request_asks_for_final_usage_chunk(self) -> None:
        transport = FakeHostedTextTransport(chunks=["hello"])
        client = OpenAICompatibleTextGenerationClient(
            provider_id="openrouter",
            api_key="secret-token",
            transport=transport,
        )

        client.generate(_request(stream=True))

        self.assertEqual(transport.requests[0]["payload"]["stream_options"], {"include_usage": True})

    def test_openai_streaming_transport_captures_usage_only_chunk(self) -> None:
        class StreamingResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

            def __iter__(self):
                yield b'data: {"choices":[{"delta":{"content":"hello"}}]}\n'
                yield b'data: {"choices":[],"usage":{"prompt_tokens":12,"completion_tokens":3,"total_tokens":15}}\n'
                yield b"data: [DONE]\n"

        client = OpenAICompatibleTextGenerationClient(
            provider_id="openrouter",
            api_key="secret-token",
            transport=OpenAICompatibleHttpTransport(),
        )
        with patch("core.providers.text_generation.urllib_request.urlopen", return_value=StreamingResponse()):
            result = client.generate(_request(stream=True))

        self.assertIsNotNone(result.usage)
        assert result.usage is not None
        self.assertEqual(result.usage.total_tokens, 15)


if __name__ == "__main__":
    unittest.main()
