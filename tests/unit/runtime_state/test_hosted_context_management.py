from __future__ import annotations

from dataclasses import replace
import json
from types import SimpleNamespace
import unittest

from core.providers.agentic_protocol import (
    AgenticModelRequest,
    AgenticRequestContentBlock,
    AgenticSourceMetadata,
)
from core.providers.google_interactions_models import (
    GoogleInteractionState,
    GooglePendingFunctionCall,
)
from core.providers.google_interactions_state import (
    decode_google_interaction_state,
    encode_google_interaction_state,
)
from core.providers.hosted_context_compactors import (
    compact_google_stateless_history,
    compact_openrouter_history,
)
from core.providers.openrouter_agentic_models import (
    OPENROUTER_AGENTIC_SCHEMA_VERSION,
    OpenRouterChatState,
    OpenRouterPendingToolCall,
)
from core.providers.openrouter_agentic_profile import (
    openrouter_agentic_routing_constraint,
)
from core.providers.openrouter_agentic_state import (
    decode_openrouter_chat_state,
    encode_openrouter_chat_state,
)
from core.runtime.hosted_agentic_models import HostedAgenticLoopError
from core.runtime.hosted_context_management import (
    manage_hosted_provider_context,
    validate_agentic_context_policy,
    validate_hosted_request_context,
)
from core.runtime.hosted_harness_recipes import hosted_full_context_policy


class HostedContextManagementTest(unittest.TestCase):
    def setUp(self) -> None:
        self.context = SimpleNamespace(
            effective_authority=SimpleNamespace(authority_digest="a" * 64)
        )
        self.policy = replace(
            hosted_full_context_policy(),
            compaction_trigger_tokens=1,
            max_compacted_state_bytes=32_768,
        )
        self.metadata = (
            AgenticSourceMetadata(
                source_block_digest="b" * 64,
                source_data_class="public",
                source_trust_level="trusted_actor",
                provenance="user_input",
                semantic_block_id="semantic:turn:0",
            ),
        )

    def test_openrouter_compaction_removes_raw_history_and_preserves_pairing(self) -> None:
        secret = "do-not-copy-this-provider-private-history"
        private = encode_openrouter_chat_state(
            OpenRouterChatState(
                schema_version=OPENROUTER_AGENTIC_SCHEMA_VERSION,
                history=(
                    {"role": "system", "content": "stable-system"},
                    {"role": "user", "content": (secret + " ") * 2_000},
                    _openrouter_call("call-1", "fixture_tool"),
                    {
                        "role": "tool",
                        "tool_call_id": "call-1",
                        "content": '{"value":1}',
                    },
                    _openrouter_call("call-2", "fixture_tool"),
                ),
                pending_tool_calls=(
                    OpenRouterPendingToolCall("call-2", "fixture_tool"),
                ),
                consumed_tool_call_ids=("call-1",),
            )
        )
        private = replace(
            private,
            source_metadata=self.metadata,
            effective_data_class="public",
            effective_trust_level="trusted_actor",
            provider_request_id="request-before-compaction",
            turn_generation="turn-current",
        )

        compacted, evidence = manage_hosted_provider_context(
            private,
            context=self.context,
            context_policy=self.policy,
            compactor=compact_openrouter_history,
            active_tool_result_ids=("call-1", "call-2"),
        )

        self.assertIsNotNone(compacted)
        self.assertIsNotNone(evidence)
        self.assertTrue(evidence.applied)
        self.assertLess(evidence.compacted_bytes, evidence.source_bytes)
        self.assertNotIn(secret.encode(), compacted.content)
        self.assertEqual(compacted.source_metadata, private.source_metadata)
        self.assertEqual(compacted.provider_request_id, private.provider_request_id)
        self.assertEqual(compacted.turn_generation, private.turn_generation)
        state = decode_openrouter_chat_state(compacted)
        self.assertEqual(state.consumed_tool_call_ids, ("call-1",))
        self.assertEqual(
            tuple(item.call_id for item in state.pending_tool_calls),
            ("call-2",),
        )
        self.assertEqual(
            [item["role"] for item in state.history],
            ["system", "user", "assistant", "tool", "assistant"],
        )
        summary = json.loads(state.history[1]["content"])
        self.assertEqual(summary["authority_digest"], "a" * 64)
        self.assertNotIn("_active_tool_result_ids", summary)
        self.assertEqual(len(summary["provenance_digest"]), 64)

    def test_google_stateless_compaction_preserves_active_result_lineage(self) -> None:
        secret = "private-google-history"
        private = encode_google_interaction_state(
            GoogleInteractionState(
                schema_version="3",
                mode="stateless",
                previous_interaction_id=None,
                history=(
                    {
                        "type": "user_input",
                        "content": [{"type": "text", "text": secret * 3_000}],
                    },
                    {"type": "function_call", "call_id": "call-1"},
                    {"type": "function_result", "call_id": "call-1"},
                    {"type": "function_call", "call_id": "call-2"},
                ),
                pending_function_calls=(
                    GooglePendingFunctionCall("call-2", "fixture_tool"),
                ),
                consumed_function_call_ids=("call-1",),
            )
        )
        private = replace(
            private,
            source_metadata=self.metadata,
            effective_data_class="public",
            effective_trust_level="trusted_actor",
            provider_request_id="google-request",
            turn_generation="turn-current",
        )

        compacted, evidence = manage_hosted_provider_context(
            private,
            context=self.context,
            context_policy=self.policy,
            compactor=compact_google_stateless_history,
            active_tool_result_ids=("call-1", "call-2"),
        )

        self.assertTrue(evidence.applied)
        self.assertNotIn(secret.encode(), compacted.content)
        state = decode_google_interaction_state(
            compacted,
            default_mode="stateless",
        )
        self.assertEqual(state.consumed_function_call_ids, ("call-1",))
        self.assertEqual(
            tuple(item.call_id for item in state.pending_function_calls),
            ("call-2",),
        )
        self.assertEqual(len(state.history), 4)
        self.assertEqual(compacted.source_metadata, private.source_metadata)

    def test_request_reserve_is_independent_from_the_turn_budget(self) -> None:
        request = AgenticModelRequest(
            schema_version="1",
            request_id="context-reserve",
            correlation_id="turn-context-reserve",
            model_id="deepseek/deepseek-v4-flash",
            reasoning_effort="high",
            content_blocks=(
                AgenticRequestContentBlock(
                    content_block_id="large-user",
                    role="user",
                    data_class="public",
                    provenance="user_input",
                    trust_level="trusted_actor",
                    content_type="text/plain",
                    content=b"x" * 16_384,
                ),
            ),
            tool_definitions=(),
            tool_results=(),
            provider_private_state=None,
            routing_constraint=openrouter_agentic_routing_constraint(),
            max_output_tokens=1_024,
        )
        policy = replace(
            hosted_full_context_policy(),
            max_request_input_tokens=4_096,
            context_reserve_tokens=1_024,
            compaction_trigger_tokens=2_048,
        )

        with self.assertRaisesRegex(
            HostedAgenticLoopError,
            "context_window_reserve_unavailable",
        ):
            validate_hosted_request_context(
                request,
                context_policy=policy,
                endpoint_input_token_limit=8_192,
            )

    def test_policy_rejects_unreachable_compaction_and_false_steering(self) -> None:
        for policy in (
            replace(
                self.policy,
                compaction_trigger_tokens=(
                    self.policy.max_request_input_tokens
                    - self.policy.context_reserve_tokens
                    + 1
                ),
            ),
            replace(self.policy, tool_result_summary_bytes=512),
            replace(self.policy, max_same_turn_steering_messages=1),
            replace(
                self.policy,
                steering_delivery_mode="provider_native",
                max_same_turn_steering_messages=0,
            ),
        ):
            with self.subTest(policy=policy), self.assertRaisesRegex(
                HostedAgenticLoopError,
                "context_policy_invalid",
            ):
                validate_agentic_context_policy(policy)


def _openrouter_call(call_id: str, name: str) -> dict[str, object]:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": "{}"},
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
