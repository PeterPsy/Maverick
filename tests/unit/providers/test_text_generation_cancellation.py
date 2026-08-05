"""Hosted text request cancellation tests."""

from __future__ import annotations

from threading import Event, Thread
import unittest
from unittest.mock import patch

from core.providers.text_generation import (
    HostedTextCancellation,
    HostedTextGenerationError,
    OpenAICompatibleHttpTransport,
    OpenAICompatibleTextGenerationClient,
    TextGenerationMessage,
    TextGenerationRequest,
)


class HostedTextCancellationTest(unittest.TestCase):
    def test_streaming_cancellation_closes_and_stops_response(self) -> None:
        class BlockingResponse:
            status = 200

            def __init__(self) -> None:
                self.iteration_started = Event()
                self.closed = Event()

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

            def __iter__(self):
                self.iteration_started.set()
                if not self.closed.wait(timeout=2):
                    raise AssertionError("Timed out waiting for transport cancellation.")
                return
                yield b""  # pragma: no cover - marks this method as an iterator

            def close(self) -> None:
                self.closed.set()

        response = BlockingResponse()
        cancellation = HostedTextCancellation()
        client = OpenAICompatibleTextGenerationClient(
            provider_id="openrouter",
            api_key="secret-token",
            transport=OpenAICompatibleHttpTransport(),
        )
        errors: list[BaseException] = []

        def generate() -> None:
            try:
                client.generate(
                    TextGenerationRequest(
                        model_id="google/gemma-4-31b-it:free",
                        messages=[TextGenerationMessage(role="user", content="Hello")],
                        timeout_seconds=10,
                        stream=True,
                    ),
                    cancellation=cancellation,
                )
            except BaseException as error:  # pragma: no cover - asserted below
                errors.append(error)

        with patch("core.providers.text_generation.urllib_request.urlopen", return_value=response):
            provider_thread = Thread(target=generate)
            provider_thread.start()
            self.assertTrue(response.iteration_started.wait(timeout=1))
            cancellation.cancel()
            provider_thread.join(timeout=2)

        self.assertFalse(provider_thread.is_alive())
        self.assertTrue(response.closed.is_set())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], HostedTextGenerationError)
        self.assertEqual(errors[0].reason_code, "provider_cancelled")


if __name__ == "__main__":
    unittest.main()
