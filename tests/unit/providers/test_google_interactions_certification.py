"""Google Interactions catalog and live-probe certification regressions."""

from __future__ import annotations

import asyncio
import os
import unittest
from unittest import mock

from core.providers.agentic_protocol import (
    EphemeralCredential,
    HOSTED_FINALIZATION_INSTRUCTION,
)
from core.providers.google_interactions_client import GoogleInteractionsAgenticClient
from core.providers.google_interactions_probe import (
    CERTIFICATION_PROBE_MAX_OUTPUT_TOKENS,
    CERTIFICATION_PROBE_TOOL_ROUNDS,
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
from scripts import run_google_interactions_probe as probe_runner


class GoogleInteractionsCertificationTest(unittest.TestCase):
    def test_live_runner_accepts_bounded_operator_pacing(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"MAVERICK_CERTIFICATION_PROBE_INTERVAL_SECONDS": "20"},
        ):
            self.assertEqual(probe_runner._request_interval_seconds(), 20.0)

        with mock.patch.dict(
            os.environ,
            {"MAVERICK_CERTIFICATION_PROBE_INTERVAL_SECONDS": "invalid"},
        ):
            self.assertEqual(probe_runner._request_interval_seconds(), 1.0)

        with mock.patch.dict(
            os.environ,
            {"MAVERICK_CERTIFICATION_PROBE_INTERVAL_SECONDS": "90"},
        ):
            self.assertEqual(probe_runner._request_interval_seconds(), 30.0)

    def test_unknown_function_name_reaches_the_preliminary_ledger_boundary(self) -> None:
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

        events = asyncio.run(_events(client, _request("request-unknown-tool")))

        call = next(event.tool_call for event in events if event.tool_call is not None)
        self.assertEqual(call.provider_tool_name, "filesystem_directory_list")
        self.assertEqual(events[-1].event_type, "completed")
        self.assertTrue(any(event.event_type == "usage" for event in events))

    def test_unknown_tool_call_survives_interrupted_telemetry_drain(self) -> None:
        stream = _tool_stream(
            "interaction-interrupted",
            tool_name="filesystem_directory_list",
        )
        stream.append(RuntimeError("synthetic transport interruption"))
        client = GoogleInteractionsAgenticClient(
            transport=_ScriptedTransport([stream])
        )

        rejected = asyncio.run(_events(client, _request("request-interrupted")))

        self.assertTrue(any(event.event_type == "tool_call" for event in rejected))
        self.assertEqual(rejected[-1].error_code, "provider_unavailable")

    def test_probe_covers_every_certified_reasoning_effort(self) -> None:
        scripts = []
        for effort in CERTIFIED_REASONING_EFFORTS:
            scripts.extend(
                [
                    _tool_stream(
                        f"interaction-probe-{effort}-1",
                        tool_name=PROBE_TOOL_NAME,
                        call_id=f"call-{effort}-1",
                        arguments={"path": ".", "max_depth": 1, "max_results": 10},
                    ),
                    _tool_stream(
                        f"interaction-probe-{effort}-2",
                        tool_name=PROBE_TOOL_NAME,
                        call_id=f"call-{effort}-2",
                        arguments={"path": ".", "max_depth": 1, "max_results": 10},
                    ),
                    _text_stream(f"interaction-probe-{effort}-3", "OK"),
                ]
            )
        transport = _ScriptedTransport(scripts)

        result = asyncio.run(
            probe_google_interactions(
                credential=EphemeralCredential("probe-key"),
                client=GoogleInteractionsAgenticClient(transport=transport),
                request_interval_seconds=0,
            )
        )

        self.assertTrue(result.succeeded)
        self.assertEqual(result.reason_code, "ok")
        self.assertEqual(CERTIFIED_REASONING_EFFORTS, ("high",))
        requests_per_effort = CERTIFICATION_PROBE_TOOL_ROUNDS + 1
        self.assertEqual(
            result.request_count,
            requests_per_effort * len(CERTIFIED_REASONING_EFFORTS),
        )
        self.assertEqual(result.reasoning_efforts, CERTIFIED_REASONING_EFFORTS)
        self.assertTrue(result.saw_filesystem_list)
        self.assertEqual(
            [
                payload["generation_config"]["thinking_level"]
                for payload in transport.payloads
            ],
            [
                effort
                for effort in CERTIFIED_REASONING_EFFORTS
                for _ in range(requests_per_effort)
            ],
        )
        self.assertEqual(
            [
                payload["generation_config"]["max_output_tokens"]
                for payload in transport.payloads
            ],
            [
                CERTIFICATION_PROBE_MAX_OUTPUT_TOKENS
                for _ in range(
                    requests_per_effort * len(CERTIFIED_REASONING_EFFORTS)
                )
            ],
        )
        self.assertEqual(
            transport.payloads[1]["input"][0]["call_id"],
            "call-high-1",
        )
        self.assertEqual(
            transport.payloads[2]["input"][0]["call_id"],
            "call-high-2",
        )
        final_payload = transport.payloads[2]
        self.assertNotIn("tools", final_payload)
        self.assertIn(
            HOSTED_FINALIZATION_INSTRUCTION,
            final_payload["system_instruction"],
        )
        self.assertEqual(len(result.result_summary_digest), 64)
        self.assertNotIn("OK", repr(result))


if __name__ == "__main__":
    unittest.main()
