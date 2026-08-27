"""Pairing, orphan-WAL, provider-codec, and lifecycle recovery regressions."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import ANY, patch

from core.providers.agentic_adapter import RuntimePrepareContext, RuntimeRecoveryContext
from core.providers.google_interactions_models import (
    GOOGLE_INTERACTIONS_CODEC_ID,
    GOOGLE_INTERACTIONS_CODEC_VERSION,
    GOOGLE_INTERACTIONS_CONTENT_TYPE,
    GOOGLE_INTERACTIONS_SCHEMA_VERSION,
    GoogleInteractionState,
    GooglePendingFunctionCall,
)
from core.providers.google_interactions_state import (
    encode_google_interaction_state,
    inspect_google_interaction_state,
)
from core.providers.openrouter_agentic_models import (
    OPENROUTER_AGENTIC_CODEC_ID,
    OPENROUTER_AGENTIC_CODEC_VERSION,
    OPENROUTER_AGENTIC_CONTENT_TYPE,
    OPENROUTER_AGENTIC_SCHEMA_VERSION,
    OpenRouterChatState,
    OpenRouterPendingToolCall,
)
from core.providers.openrouter_agentic_state import (
    encode_openrouter_chat_state,
    inspect_openrouter_chat_state,
)
from core.recovery.backend_restart import recover_interrupted_runtime_turns_after_backend_restart
from core.recovery.continuation_fork import admit_runtime_session
from core.runtime.hosted_agentic_models import HostedProviderPrivateCodec
from tests.support.fake_agentic_provider import DeterministicFakeAgenticClient
from tests.support.hosted_agentic_harness import HostedAgenticHarness
from tests.unit.runtime_state import test_hosted_agentic_recovery as recovery_fixture


_StartupSentinel = recovery_fixture._StartupSentinel
_no_confirmation_policy = recovery_fixture._no_confirmation_policy


class HostedAgenticRecoveryPairingTest(unittest.TestCase):
    _begin = recovery_fixture.HostedAgenticRecoveryTest._begin
    _tool_step = recovery_fixture.HostedAgenticRecoveryTest._tool_step

    def test_crash_after_provider_state_without_terminal_evidence_quarantines(self) -> None:
        harness = HostedAgenticHarness(self)
        adapter = harness.adapter(DeterministicFakeAgenticClient())
        journal = adapter.loop.provider_step_journal
        record = self._begin(harness, adapter, "request-state-only")
        record = journal.accept(
            record,
            provider_response_id="response-state-only",
            provider_upstream_id=None,
        )
        codec = adapter.loop.provider_runtimes.resolve(harness.binding).private_codec
        envelope = harness.private_state_service.stage_state(
            session_id="session-hosted",
            adapter_id=harness.binding.adapter_id,
            adapter_version=harness.binding.adapter_version,
            codec_id=codec.codec_id,
            codec_version=codec.codec_version,
            schema_version=codec.schema_version,
            content_type=codec.content_type,
            payload=b"state-without-terminal-evidence",
            turn_generation="turn-hosted",
            provider_request_id="request-state-only",
        )
        journal.stage_provider_state(record, envelope)

        first = asyncio.run(
            adapter.recover(
                RuntimeRecoveryContext(
                    harness.session,
                    harness.binding,
                    harness.store.get_provider_state("session-hosted"),
                    "crash_after_provider_state",
                )
            )
        )
        persisted = harness.store.get_provider_step_journal(record.journal_id)
        revision = persisted.revision
        second = asyncio.run(
            adapter.recover(
                RuntimeRecoveryContext(
                    harness.store.get_session("session-hosted"),
                    harness.binding,
                    harness.store.get_provider_state("session-hosted"),
                    "restart_repeat",
                )
            )
        )

        self.assertFalse(first.recovered)
        self.assertFalse(second.recovered)
        self.assertEqual(first.reason_code, "provider_acceptance_ambiguous")
        self.assertEqual(persisted.commit_status, "recovery_required")
        self.assertEqual(
            harness.store.get_provider_step_journal(record.journal_id).revision,
            revision,
        )
        self.assertIsNone(
            harness.store.get_provider_state("session-hosted").provider_private_envelope
        )

    def test_committed_child_repairs_unconsumed_pairing_once(self) -> None:
        harness = HostedAgenticHarness(self)
        adapter = harness.adapter(DeterministicFakeAgenticClient())
        source, _outcome, _envelope = self._tool_step(
            harness,
            adapter,
            request_id="request-source",
        )
        recovered_source = asyncio.run(
            adapter.recover(
                RuntimeRecoveryContext(
                    harness.session,
                    harness.binding,
                    harness.store.get_provider_state("session-hosted"),
                    "source_recovery",
                )
            )
        )
        self.assertTrue(recovered_source.recovered)
        source = harness.store.get_provider_step_journal(source.journal_id)
        self.assertEqual(source.pairing_status, "ready")

        journal = adapter.loop.provider_step_journal
        codec = adapter.loop.provider_runtimes.resolve(harness.binding).private_codec
        child = journal.begin_request(
            session=harness.session,
            binding=harness.binding,
            provider_state=harness.store.get_provider_state("session-hosted"),
            request_id="request-child-final",
            turn_id="turn-hosted",
            step_index=1,
            codec=codec,
            pairing_source_journal_id=source.journal_id,
        )
        child = journal.journal_request(child)
        child = journal.accept(
            child,
            provider_response_id="response-child-final",
            provider_upstream_id=None,
        )
        child_envelope = harness.private_state_service.stage_state(
            session_id="session-hosted",
            adapter_id=harness.binding.adapter_id,
            adapter_version=harness.binding.adapter_version,
            codec_id=codec.codec_id,
            codec_version=codec.codec_version,
            schema_version=codec.schema_version,
            content_type=codec.content_type,
            payload=b"committed-child-final-state",
            turn_generation="turn-hosted",
            provider_request_id="request-child-final",
        )
        child = journal.stage_provider_state(child, child_envelope)
        child = journal.complete_stream(child, final_output_validated=True)
        harness.private_state_service.promote_staged_state(
            session_id="session-hosted",
            adapter_id=harness.binding.adapter_id,
            adapter_version=harness.binding.adapter_version,
            envelope=child_envelope,
            expected_revision=child.base_provider_state_revision,
        )
        journal.mark_committed(child)

        first = asyncio.run(
            adapter.recover(
                RuntimeRecoveryContext(
                    harness.session,
                    harness.binding,
                    harness.store.get_provider_state("session-hosted"),
                    "crash_before_pairing_consumption",
                )
            )
        )
        consumed = harness.store.get_provider_step_journal(source.journal_id)
        revision = consumed.revision
        second = asyncio.run(
            adapter.recover(
                RuntimeRecoveryContext(
                    harness.session,
                    harness.binding,
                    harness.store.get_provider_state("session-hosted"),
                    "restart_repeat",
                )
            )
        )

        self.assertTrue(first.recovered)
        self.assertTrue(second.recovered)
        self.assertEqual(consumed.pairing_status, "consumed")
        self.assertEqual(
            harness.store.get_provider_step_journal(source.journal_id).revision,
            revision,
        )

    def test_wal_saga_recovers_blob_written_before_journal_attachment(self) -> None:
        harness = HostedAgenticHarness(self)
        adapter = harness.adapter(DeterministicFakeAgenticClient())
        journal = adapter.loop.provider_step_journal
        record = self._begin(harness, adapter, "request-orphan-stage")
        record = journal.accept(
            record,
            provider_response_id="response-orphan-stage",
            provider_upstream_id=None,
        )
        codec = adapter.loop.provider_runtimes.resolve(harness.binding).private_codec
        envelope = harness.private_state_service.stage_state(
            session_id="session-hosted",
            adapter_id=harness.binding.adapter_id,
            adapter_version=harness.binding.adapter_version,
            codec_id=codec.codec_id,
            codec_version=codec.codec_version,
            schema_version=codec.schema_version,
            content_type=codec.content_type,
            payload=b"orphan-staged-provider-state",
            turn_generation="turn-hosted",
            provider_request_id="request-orphan-stage",
        )
        outcome = harness.orchestrator.observe_provider_tool(
            provider_tool_name=harness.read_tool_name,
            provider_tool_call_id="orphan-call",
            arguments={"value": 1},
            provider_request_id="request-orphan-stage",
            provider_event_ordinal=2,
            provider_call_index=0,
            authority=harness.authority,
            context=adapter.loop.actor_context_resolver(None),
            turn_id="turn-hosted",
            policy=_no_confirmation_policy(),
        )
        record = journal.add_proposal(record, outcome.invocation.proposal_id)
        record = journal.complete_stream(record, final_output_validated=False)
        self.assertIsNone(record.staged_provider_state)

        recovered = asyncio.run(
            adapter.recover(
                RuntimeRecoveryContext(
                    harness.session,
                    harness.binding,
                    harness.store.get_provider_state("session-hosted"),
                    "fault_between_blob_and_wal",
                )
            )
        )

        terminal = harness.store.get_provider_step_journal(record.journal_id)
        self.assertTrue(recovered.recovered)
        self.assertEqual(
            terminal.staged_provider_state.opaque_state_ref,
            envelope.opaque_state_ref,
        )
        self.assertEqual(terminal.commit_status, "committed")

    def test_google_and_openrouter_recovery_decode_exact_pending_pairing(self) -> None:
        cases = (
            (
                "google",
                HostedProviderPrivateCodec(
                    GOOGLE_INTERACTIONS_CODEC_ID,
                    GOOGLE_INTERACTIONS_CODEC_VERSION,
                    GOOGLE_INTERACTIONS_SCHEMA_VERSION,
                    GOOGLE_INTERACTIONS_CONTENT_TYPE,
                ),
                lambda content: inspect_google_interaction_state(content, mode="stateful"),
                encode_google_interaction_state(
                    GoogleInteractionState(
                        schema_version=GOOGLE_INTERACTIONS_SCHEMA_VERSION,
                        mode="stateful",
                        previous_interaction_id="google-recovery",
                        history=(),
                        pending_function_calls=(
                            GooglePendingFunctionCall("provider-call", "PLACEHOLDER"),
                        ),
                        consumed_function_call_ids=(),
                    )
                ),
            ),
            (
                "openrouter",
                HostedProviderPrivateCodec(
                    OPENROUTER_AGENTIC_CODEC_ID,
                    OPENROUTER_AGENTIC_CODEC_VERSION,
                    OPENROUTER_AGENTIC_SCHEMA_VERSION,
                    OPENROUTER_AGENTIC_CONTENT_TYPE,
                ),
                inspect_openrouter_chat_state,
                None,
            ),
        )
        for name, codec, inspector, initial_private in cases:
            with self.subTest(provider=name):
                harness = HostedAgenticHarness(self)
                safe_name = harness.read_tool_name
                if name == "google":
                    provider_private = replace(
                        initial_private,
                        content=initial_private.content.replace(b"PLACEHOLDER", safe_name.encode()),
                    )
                else:
                    provider_private = encode_openrouter_chat_state(
                        OpenRouterChatState(
                            OPENROUTER_AGENTIC_SCHEMA_VERSION,
                            (
                                {
                                    "role": "assistant",
                                    "content": None,
                                    "tool_calls": [
                                        {
                                            "id": "provider-call",
                                            "type": "function",
                                            "function": {
                                                "name": safe_name,
                                                "arguments": '{"value":1}',
                                            },
                                        }
                                    ],
                                },
                            ),
                            pending_tool_calls=(
                                OpenRouterPendingToolCall("provider-call", safe_name),
                            ),
                        )
                    )
                adapter = harness.adapter(
                    DeterministicFakeAgenticClient(),
                    private_codec=codec,
                    private_state_inspector=inspector,
                )
                record, _outcome, _envelope = self._tool_step(
                    harness,
                    adapter,
                    request_id=f"request-{name}",
                    provider_state_payload=provider_private.content,
                    provider_tool_call_id="provider-call",
                )

                recovered = asyncio.run(
                    adapter.recover(
                        RuntimeRecoveryContext(
                            harness.session,
                            harness.binding,
                            harness.store.get_provider_state("session-hosted"),
                            f"{name}_crash_matrix",
                        )
                    )
                )

                self.assertTrue(recovered.recovered)
                self.assertEqual(
                    harness.store.get_provider_step_journal(record.journal_id).commit_status,
                    "committed",
                )

    def test_pre_prepare_and_startup_paths_invoke_recovery(self) -> None:
        harness = HostedAgenticHarness(self)
        adapter = harness.adapter(DeterministicFakeAgenticClient())
        record = self._begin(harness, adapter, "request-prepare")
        prepared = asyncio.run(
            adapter.prepare(
                RuntimePrepareContext(
                    harness.session,
                    harness.binding,
                    harness.store.get_provider_state("session-hosted"),
                )
            )
        )
        self.assertTrue(prepared.ready)
        self.assertEqual(
            harness.store.get_provider_step_journal(record.journal_id).commit_status,
            "rolled_back",
        )

        with patch(
            "core.recovery.backend_restart.recover_all_hosted_agentic_sessions",
            side_effect=_StartupSentinel("startup recovery invoked"),
        ) as lifecycle:
            with self.assertRaisesRegex(_StartupSentinel, "startup recovery invoked"):
                recover_interrupted_runtime_turns_after_backend_restart(
                    SimpleNamespace(runtime_store=object())
                )
        lifecycle.assert_called_once_with(
            ANY,
            trigger="startup_worker_loss",
        )

        with patch(
            "core.recovery.continuation_fork.recover_hosted_agentic_session",
            side_effect=_StartupSentinel("pre-admission recovery invoked"),
        ) as admission_recovery:
            with self.assertRaisesRegex(
                _StartupSentinel,
                "pre-admission recovery invoked",
            ):
                admit_runtime_session(
                    SimpleNamespace(),
                    session=harness.session,
                )
        admission_recovery.assert_called_once_with(
            ANY,
            session=harness.session,
            trigger="pre_admission",
        )



if __name__ == "__main__":
    unittest.main()
