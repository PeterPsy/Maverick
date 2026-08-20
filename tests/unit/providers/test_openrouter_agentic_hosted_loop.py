"""OpenRouter codec integration through the shared hosted runtime loop."""

from __future__ import annotations

import json
import unittest

from core.providers.agentic_protocol import EphemeralCredential
from core.providers.openrouter_agentic_client import (
    OpenRouterAgenticClient,
    openrouter_deepinfra_v4_flash_request_ceiling_microusd,
)
from core.providers.openrouter_agentic_models import (
    OPENROUTER_AGENTIC_CODEC_ID,
    OPENROUTER_AGENTIC_CODEC_VERSION,
    OPENROUTER_AGENTIC_CONTENT_TYPE,
    OPENROUTER_AGENTIC_MODEL_ID,
    OPENROUTER_AGENTIC_SCHEMA_VERSION,
)
from core.providers.openrouter_agentic_profile import openrouter_agentic_routing_constraint
from core.runtime.execution import execute_runtime_turn
from core.runtime.hosted_agentic_models import HostedProviderPrivateCodec
from tests.support.hosted_agentic_harness import HostedAgenticHarness
from tests.unit.providers.test_openrouter_agentic_codec import (
    _ScriptedTransport,
    _text_stream,
    _tool_stream,
)


class OpenRouterAgenticHostedLoopTest(unittest.TestCase):
    def test_real_codec_runs_through_shared_tool_loop(self) -> None:
        harness = HostedAgenticHarness(
            self,
            model_provider_id="openrouter",
            model_id=OPENROUTER_AGENTIC_MODEL_ID,
            provider_protocol="openrouter-chat-completions",
            routing_constraint=openrouter_agentic_routing_constraint(),
            filesystem_list=True,
        )
        transport = _ScriptedTransport([
            _tool_stream(
                "generation-loop-1",
                harness.filesystem_list_tool_name,
                arguments={"path": ".", "max_depth": 1, "max_results": 10},
            ),
            _text_stream("generation-loop-2", "OpenRouter fixture answer"),
        ])
        adapter = harness.adapter(
            OpenRouterAgenticClient(transport=transport),
            private_codec=HostedProviderPrivateCodec(
                OPENROUTER_AGENTIC_CODEC_ID,
                OPENROUTER_AGENTIC_CODEC_VERSION,
                OPENROUTER_AGENTIC_SCHEMA_VERSION,
                OPENROUTER_AGENTIC_CONTENT_TYPE,
            ),
            credential=EphemeralCredential("fixture-openrouter-key"),
            cost_estimator=openrouter_deepinfra_v4_flash_request_ceiling_microusd,
        )
        public_events = []

        result = execute_runtime_turn(
            session=harness.session,
            provider=harness.provider,
            input_text="Use only synthetic fixture data.",
            agentic_adapter=adapter,
            provider_state=harness.store.get_provider_state("session-hosted"),
            correlation_id="turn-hosted",
            effective_authority=harness.authority,
            event_sink=public_events.append,
        )

        self.assertEqual(result.output_text, "OpenRouter fixture answer")
        self.assertEqual(harness.cli_calls, 0)
        self.assertEqual(
            transport.payloads[0]["tools"][0]["function"]["name"],
            harness.filesystem_list_tool_name,
        )
        self.assertIn(harness.filesystem_marker, json.dumps(transport.payloads[1]))
        self.assertEqual(transport.payloads[1]["provider"]["only"], ["deepinfra/fp8"])
        serialized = json.dumps([event.payload for event in public_events], default=str)
        self.assertNotIn("private fixture reasoning", serialized)
        self.assertNotIn("private-signature", serialized)


if __name__ == "__main__":
    unittest.main()
