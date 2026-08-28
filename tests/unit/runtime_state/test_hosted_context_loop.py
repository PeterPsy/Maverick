from __future__ import annotations

import asyncio
from dataclasses import replace
import hashlib
from threading import Thread
import time
import unittest

from core.providers.agentic_adapter import RuntimeCancelContext, RuntimeRecoveryContext
from core.providers.agentic_models import AgenticContextPolicy, codex_routing_constraint
from core.providers.agentic_protocol import AgenticSourceMetadata
from core.runtime.execution import execute_runtime_turn
from core.runtime.hosted_context_management import (
    HOSTED_CONTEXT_COMPACTION_SCHEMA_VERSION,
    HostedContextCompactionEvidence,
    HostedContextCompactionResult,
)
from core.runtime.hosted_harness_recipes import (
    HostedHarnessRecipeManifest,
    HostedProviderSupportFlags,
)
from tests.support.fake_agentic_provider import DeterministicFakeAgenticClient
from tests.support.hosted_agentic_harness import HostedAgenticHarness


CONTEXT_POLICY = AgenticContextPolicy(
    revision="fixture-context-v1",
    max_request_input_tokens=16_384,
    context_reserve_tokens=1_024,
    compaction_mode="provider_history",
    compaction_trigger_tokens=1,
    max_compacted_state_bytes=1_024,
    summary_max_bytes=512,
    tool_result_inline_bytes=128,
    tool_result_summary_bytes=1_024,
    attachment_projection_mode="workspace_reference",
    steering_delivery_mode="safe_next_turn",
    max_same_turn_steering_messages=0,
)
FIXTURE_RECIPE = HostedHarnessRecipeManifest(
    recipe_id="fixture-hosted-context-loop",
    revision="1",
    model_provider_id="fake-model-provider",
    model_id="fake-model-v1",
    provider_protocol="fake-agentic-v1",
    provider_api_version="v1",
    endpoint_id=codex_routing_constraint().endpoint_id,
    upstream_ids=(),
    state_mode="client-managed-history",
    semantic_projection_compiler_revision="3",
    tool_contract_revision="fixture-tool-contract-v1",
    context_policy=CONTEXT_POLICY,
    support_flags=HostedProviderSupportFlags(
        streaming=True,
        usage_accounting=True,
        tool_calling=True,
        supports_empty_tool_catalog=True,
        supports_tool_choice_none=True,
        omits_tools_when_empty=False,
        parallel_tool_calls=False,
        cooperative_cancellation=True,
        continuation_mode="fixture-private-state",
        reasoning_efforts=("high",),
        attachment_modalities=("file",),
        input_token_limit=16_384,
        output_token_limit=1_024,
    ),
)


class HostedContextLoopTest(unittest.TestCase):
    def test_final_output_and_recovery_remain_valid_after_compaction(self) -> None:
        harness = self._harness_with_large_state()
        client = DeterministicFakeAgenticClient(final_text="compacted final answer")
        adapter = harness.adapter(
            client,
            context_compactor=_compact_fixture_state,
            request_preflight=_fixture_preflight,
        )

        result = execute_runtime_turn(
            session=harness.session,
            provider=harness.provider,
            input_text="Use the compacted fixture.",
            agentic_adapter=adapter,
            provider_state=harness.store.get_provider_state("session-hosted"),
            correlation_id="turn-hosted",
            effective_authority=harness.authority,
        )

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.output_text, "compacted final answer")
        self.assertEqual(
            client.requests[0].provider_private_state.content,
            b'{"compacted":true}',
        )
        self.assertTrue(client.requests[0].context_compaction_applied)
        self.assertEqual(client.requests[0].context_policy_revision, CONTEXT_POLICY.revision)
        journal = harness.store.list_provider_step_journals(
            session_id="session-hosted"
        )[0]
        self.assertTrue(journal.context_compaction_applied)
        self.assertEqual(len(journal.context_compaction_evidence_digest), 64)

        recovered = asyncio.run(
            adapter.recover(
                RuntimeRecoveryContext(
                    harness.session,
                    harness.binding,
                    harness.store.get_provider_state("session-hosted"),
                    "post_compaction_restart",
                )
            )
        )
        self.assertTrue(recovered.recovered)

    def test_cancellation_after_compaction_stays_fail_closed(self) -> None:
        harness = self._harness_with_large_state()
        client = DeterministicFakeAgenticClient(stall_after_acceptance=True)
        adapter = harness.adapter(
            client,
            context_compactor=_compact_fixture_state,
            request_preflight=_fixture_preflight,
        )
        holder: dict[str, object] = {}

        def run() -> None:
            holder["result"] = execute_runtime_turn(
                session=harness.session,
                provider=harness.provider,
                input_text="Cancel after compacting.",
                agentic_adapter=adapter,
                provider_state=harness.store.get_provider_state("session-hosted"),
                correlation_id="turn-hosted",
                effective_authority=harness.authority,
            )

        thread = Thread(target=run)
        thread.start()
        deadline = time.monotonic() + 3
        accepted_journal = None
        while time.monotonic() < deadline:
            journals = harness.store.list_provider_step_journals(
                session_id="session-hosted"
            )
            accepted_journal = next(
                (
                    item
                    for item in journals
                    if item.acceptance_status == "accepted"
                ),
                None,
            )
            if accepted_journal is not None:
                break
            time.sleep(0.01)
        self.assertTrue(client.requests)
        self.assertIsNotNone(accepted_journal)
        cancelled = asyncio.run(
            adapter.cancel(
                RuntimeCancelContext(
                    harness.session,
                    harness.binding,
                    harness.store.get_provider_state("session-hosted"),
                    "turn-hosted",
                )
            )
        )
        thread.join(timeout=5)

        self.assertTrue(cancelled.cancelled)
        self.assertFalse(thread.is_alive())
        self.assertEqual(holder["result"].exit_code, 1)
        self.assertTrue(client.requests[0].context_compaction_applied)
        self.assertEqual(
            harness.store.get_session("session-hosted").status,
            "recovery_required",
        )
        recovery = asyncio.run(
            adapter.recover(
                RuntimeRecoveryContext(
                    harness.store.get_session("session-hosted"),
                    harness.binding,
                    harness.store.get_provider_state("session-hosted"),
                    "cancelled_after_compaction",
                )
            )
        )
        self.assertFalse(recovery.recovered)
        self.assertEqual(recovery.reason_code, "provider_acceptance_ambiguous")

    def _harness_with_large_state(self) -> HostedAgenticHarness:
        harness = HostedAgenticHarness(self, recipe=FIXTURE_RECIPE)
        metadata = AgenticSourceMetadata(
            source_block_digest="c" * 64,
            source_data_class="public",
            source_trust_level="trusted_actor",
            provenance="provider_state",
        )
        harness.private_state_service.store_state(
            session_id="session-hosted",
            adapter_id=harness.binding.adapter_id,
            adapter_version=harness.binding.adapter_version,
            codec_id="fake-hosted-codec",
            codec_version="1",
            schema_version="1",
            content_type="application/vnd.maverick.fake-private",
            payload=b"private-history-must-not-reach-the-next-request:" * 2_000,
            expected_revision=0,
            turn_generation="turn-before-compaction",
            source_metadata=(metadata,),
            provider_request_id="request-before-compaction",
        )
        return harness


def _fixture_preflight(_request, _credential):
    return type("FixtureSnapshot", (), {"snapshot_digest": "d" * 64})()


def _compact_fixture_state(state, policy, summary_base):
    compacted = replace(state, content=b'{"compacted":true}')
    summary_digest = hashlib.sha256(b"fixture-metadata-summary").hexdigest()
    evidence = HostedContextCompactionEvidence(
        schema_version=HOSTED_CONTEXT_COMPACTION_SCHEMA_VERSION,
        policy_revision=policy.revision,
        applied=True,
        source_state_digest=hashlib.sha256(state.content).hexdigest(),
        compacted_state_digest=hashlib.sha256(compacted.content).hexdigest(),
        source_bytes=len(state.content),
        compacted_bytes=len(compacted.content),
        omitted_items=1,
        retained_items=0,
        authority_digest=str(summary_base["authority_digest"]),
        provenance_digest=str(summary_base["provenance_digest"]),
        summary_digest=summary_digest,
    )
    return HostedContextCompactionResult(state=compacted, evidence=evidence)


if __name__ == "__main__":
    unittest.main()
