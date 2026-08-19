"""Google Interactions catalog and live-probe certification regressions."""

from __future__ import annotations

import asyncio
import unittest

from core.providers.agentic_protocol import EphemeralCredential
from core.providers.google_interactions_client import GoogleInteractionsAgenticClient
from core.providers.google_interactions_probe import (
    CERTIFICATION_PROBE_MAX_OUTPUT_TOKENS,
    CERTIFIED_REASONING_EFFORTS,
    PROBE_TOOL_NAME,
    probe_google_interactions,
)
from tests.unit.providers.test_google_interactions_codec import (
    _ScriptedTransport,
    _events,
    _request,
    _text_stream,
    _tool_stream,
)


class GoogleInteractionsCertificationTest(unittest.TestCase):
    def test_function_name_must_match_the_exact_declared_catalog(self) -> None:
        client = GoogleInteractionsAgenticClient(
            transport=_ScriptedTransport(
                [
                    _tool_stream(
                        "interaction-unknown-tool",
                        tool_name="filesystem_directory_list",
                    )
                ]
            )
        )

        rejected = asyncio.run(_events(client, _request("request-unknown-tool")))

        self.assertEqual(rejected[-1].error_code, "provider_tool_not_declared")
        self.assertFalse(any(event.event_type == "tool_call" for event in rejected))
        self.assertTrue(any(event.event_type == "usage" for event in rejected))

    def test_unknown_tool_error_survives_interrupted_telemetry_drain(self) -> None:
        stream = _tool_stream(
            "interaction-interrupted",
            tool_name="filesystem_directory_list",
        )
        stream.append(RuntimeError("synthetic transport interruption"))
        client = GoogleInteractionsAgenticClient(
            transport=_ScriptedTransport([stream])
        )

        rejected = asyncio.run(_events(client, _request("request-interrupted")))

        self.assertEqual(rejected[-1].error_code, "provider_tool_not_declared")

    def test_probe_covers_every_certified_reasoning_effort(self) -> None:
        scripts = []
        for effort in CERTIFIED_REASONING_EFFORTS:
            scripts.extend(
                [
                    _tool_stream(
                        f"interaction-probe-{effort}-1",
                        tool_name=PROBE_TOOL_NAME,
                    ),
                    _text_stream(f"interaction-probe-{effort}-2", "OK"),
                ]
            )
        transport = _ScriptedTransport(scripts)

        result = asyncio.run(
            probe_google_interactions(
                credential=EphemeralCredential("probe-key"),
                client=GoogleInteractionsAgenticClient(transport=transport),
            )
        )

        self.assertTrue(result.succeeded)
        self.assertEqual(result.reason_code, "ok")
        self.assertEqual(result.request_count, 8)
        self.assertEqual(result.reasoning_efforts, CERTIFIED_REASONING_EFFORTS)
        self.assertEqual(
            [
                payload["generation_config"]["thinking_level"]
                for payload in transport.payloads
            ],
            [effort for effort in CERTIFIED_REASONING_EFFORTS for _ in range(2)],
        )
        self.assertEqual(
            [
                payload["generation_config"]["max_output_tokens"]
                for payload in transport.payloads
            ],
            [
                CERTIFICATION_PROBE_MAX_OUTPUT_TOKENS
                for _ in range(2 * len(CERTIFIED_REASONING_EFFORTS))
            ],
        )
        self.assertEqual(len(result.result_summary_digest), 64)
        self.assertNotIn("OK", repr(result))


if __name__ == "__main__":
    unittest.main()
