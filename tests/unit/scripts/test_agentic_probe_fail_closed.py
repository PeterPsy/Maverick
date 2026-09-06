"""A final protocol failure must not become a successful live certificate step."""

import asyncio
from contextlib import redirect_stdout
from io import StringIO
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.providers.agentic_protocol import (
    AgenticModelEvent, AgenticProviderPrivateState, AgenticToolCall, AgenticUsage,
    EphemeralCredential,
)
from core.providers.google_interactions_probe import probe_google_interactions
from scripts import run_openrouter_agentic_probe as openrouter


class AdversarialProbeClient:
    def __init__(self, fault):
        self.fault = fault
        self.requests = []

    async def create_response(self, request, *, credential):
        self.requests.append(request)
        final = request.request_phase == "finalization"
        last_final = final and request.reasoning_effort == "high"
        events = []
        if final:
            if not (last_final and self.fault == "missing_final"):
                events.extend([
                    ("text_delta", {"text": "OK"}),
                    ("text_final", {"text": " " if last_final and self.fault == "blank_final" else "OK"}),
                ])
        if not final or (last_final and self.fault == "final_tool"):
            name = request.tool_definitions[0].name if not final else "forbidden-tool"
            events.append(("tool_call", {"tool_call": AgenticToolCall(
                f"call-{len(self.requests)}", name,
                {"path": ".", "max_depth": 1, "max_results": 10},
            )}))
            if self.fault == "parallel":
                events.append(("tool_call", {"tool_call": AgenticToolCall("extra", name, {})}))
        events.extend([
            ("provider_state", {"provider_private_state": AgenticProviderPrivateState(
                "fixture", "1", "1", "application/json", b"{}",
                provider_request_id=request.request_id, turn_generation=request.correlation_id,
            )}),
            ("usage", {"usage": AgenticUsage(10, 2, 1)}),
            ("completed", {}),
        ])
        for ordinal, (kind, fields) in enumerate(events, 1):
            if last_final and kind == self.fault:
                continue
            yield AgenticModelEvent(kind, request.request_id, ordinal, **fields)


class AgenticProbeFailClosedTest(unittest.TestCase):
    def test_both_probes_reject_bad_last_response_and_extra_calls(self):
        for provider in ("google", "openrouter"):
            for fault in ("missing_final", "blank_final", "final_tool", "parallel",
                          "usage", "provider_state", "completed"):
                with self.subTest(provider=provider, fault=fault):
                    client = AdversarialProbeClient(fault)
                    self.assertFalse(self.run_probe(provider, client))
                    if fault == "parallel":
                        self.assertEqual(len(client.requests), 1)

    def test_complete_probes_pass_without_network(self):
        for provider in ("google", "openrouter"):
            with self.subTest(provider=provider):
                client = AdversarialProbeClient(None)
                self.assertTrue(self.run_probe(provider, client))
                self.assertTrue(all(request.max_output_tokens >= 2_048 for request in client.requests))
                self.assertTrue(all(request.model_revision for request in client.requests))

    def run_probe(self, provider, client):
        if provider == "google":
            return asyncio.run(probe_google_interactions(
                credential=EphemeralCredential("synthetic"), client=client,
                request_interval_seconds=0,
            )).succeeded
        output = StringIO()
        with patch.dict("os.environ", {
            "MAVERICK_OPENROUTER_CERTIFICATION_API_KEY": "synthetic",
            "MAVERICK_CERTIFICATION_PROBE_INTERVAL_SECONDS": "0",
                "MAVERICK_CERTIFICATION_ALLOW_LIVE": "1",
                "MAVERICK_CERTIFICATION_MAX_COST_MICROUSD": "1000000",
        }), patch.object(openrouter, "OpenRouterAgenticClient", return_value=client), patch.object(
            openrouter, "preflight_openrouter_agentic_catalog", return_value=SimpleNamespace(
                upstream_id="deepinfra/fp8", model_catalog_record_digest="a" * 64,
                zdr_catalog_record_digest="b" * 64, catalog_snapshot_digest="c" * 64,
                supports_tool_choice_none=True, context_length=1_048_576,
                max_completion_tokens=65_536,
            ),
        ), redirect_stdout(output):
            result = asyncio.run(openrouter._main())
        self.assertEqual(result == 0, json.loads(output.getvalue())["succeeded"])
        return result == 0


if __name__ == "__main__":
    unittest.main()
