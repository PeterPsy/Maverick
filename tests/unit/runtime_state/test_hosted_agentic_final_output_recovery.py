"""Final-output private outbox and crash-restart regressions."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.providers.agentic_adapter import RuntimeRecoveryContext, RuntimeTurnContext
from core.runtime.execution import execute_runtime_turn
from core.runtime.provider_step_admission import provider_step_admission_reason
from core.runtime.provider_step_journal import ProviderStepJournal
from core.runtime.turn_submission_service_output_text import _RuntimeTurnOutputRecorder
from tests.support.fake_agentic_provider import DeterministicFakeAgenticClient
from tests.support.hosted_agentic_harness import HostedAgenticHarness


class _InjectedProcessCrash(BaseException):
    pass


class HostedAgenticFinalOutputRecoveryTest(unittest.TestCase):
    def test_normal_final_delivery_persists_both_stable_events_before_ack(self) -> None:
        harness = HostedAgenticHarness(self)
        client = DeterministicFakeAgenticClient(final_text="durable normal answer")
        adapter = harness.adapter(client)
        recorder = _RuntimeTurnOutputRecorder(
            SimpleNamespace(runtime_store=harness.store, runtime_event_bus=None),
            session_id=harness.session.session_id,
            turn_id="turn-hosted",
        )

        result = execute_runtime_turn(
            session=harness.store.get_session(harness.session.session_id),
            provider=harness.provider,
            input_text="Use only synthetic fixture data.",
            event_sink=recorder.record,
            agentic_adapter=adapter,
            provider_state=harness.store.get_provider_state(
                harness.session.session_id
            ),
            correlation_id="turn-hosted",
            effective_authority=harness.authority,
        )

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.output_text, "durable normal answer")
        event_types = [
            event.event_type
            for event in harness.store.list_events(harness.session.session_id)
        ]
        self.assertEqual(event_types.count("runtime.output.final"), 1)
        self.assertEqual(event_types.count("provider.execution.completed"), 1)
        terminal = harness.store.list_provider_step_journals(
            session_id=harness.session.session_id
        )[-1]
        self.assertEqual(terminal.final_output_status, "delivered")
        self.assertEqual(terminal.final_completion_status, "delivered")

    def test_final_commit_crash_replays_private_outbox_without_provider_retry(self) -> None:
        for crash_point in (
            "committed",
            "final_output_delivered",
            "final_completion_delivered",
        ):
            with self.subTest(crash_point=crash_point):
                harness = HostedAgenticHarness(self)
                client = DeterministicFakeAgenticClient(final_text="durable answer")
                adapter = harness.adapter(client)
                crashed = False

                def fault(point, _record):
                    nonlocal crashed
                    if point == crash_point and not crashed:
                        crashed = True
                        raise _InjectedProcessCrash(point)

                crashing_journal = ProviderStepJournal(
                    store=harness.store,
                    fault_hook=fault,
                )
                adapter.loop.provider_step_journal = crashing_journal
                adapter.loop.recovery.journal = crashing_journal
                first_events = []
                with self.assertRaises(_InjectedProcessCrash):
                    asyncio.run(
                        self._drain_adapter(
                            adapter,
                            self._turn_context(harness),
                            first_events,
                        )
                    )

                restarted_journal = ProviderStepJournal(store=harness.store)
                adapter.loop.provider_step_journal = restarted_journal
                adapter.loop.recovery.journal = restarted_journal
                replay_events = []
                asyncio.run(
                    self._drain_adapter(
                        adapter,
                        self._turn_context(harness),
                        replay_events,
                    )
                )
                repeated_restart_events = []
                asyncio.run(
                    self._drain_adapter(
                        adapter,
                        self._turn_context(harness),
                        repeated_restart_events,
                    )
                )
                combined = [*first_events, *replay_events]
                self.assertEqual(len(client.requests), 1)
                self.assertEqual(
                    [event.event_type for event in combined].count(
                        "runtime.output.final"
                    ),
                    1,
                )
                final_event = next(
                    event
                    for event in combined
                    if event.event_type == "runtime.output.final"
                )
                self.assertEqual(final_event.payload["text"], "durable answer")
                completions = [
                    event
                    for event in combined
                    if event.event_type == "provider.execution.completed"
                ]
                self.assertEqual(len(completions), 1)
                self.assertEqual(
                    completions[0].payload["output_text"],
                    "durable answer",
                )
                self.assertEqual(repeated_restart_events, [])
                terminal = harness.store.list_provider_step_journals(
                    session_id=harness.session.session_id
                )[-1]
                self.assertEqual(terminal.final_output_status, "delivered")
                self.assertEqual(terminal.final_completion_status, "delivered")
                self.assertNotIn("durable answer", repr(terminal))

    def test_recovery_attaches_outbox_write_interrupted_before_journal_cas(self) -> None:
        harness = HostedAgenticHarness(self)
        client = DeterministicFakeAgenticClient(final_text="pre-CAS durable answer")
        adapter = harness.adapter(client)
        journal = adapter.loop.provider_step_journal
        first_events = []
        with patch.object(
            journal,
            "stage_final_output",
            side_effect=_InjectedProcessCrash("before_final_output_ready"),
        ), self.assertRaises(_InjectedProcessCrash):
            asyncio.run(
                self._drain_adapter(
                    adapter,
                    self._turn_context(harness),
                    first_events,
                )
            )

        recovered = asyncio.run(
            adapter.recover(
                RuntimeRecoveryContext(
                    harness.session,
                    harness.binding,
                    harness.store.get_provider_state(harness.session.session_id),
                    "final_outbox_pre_cas_restart",
                )
            )
        )
        replay_events = []
        asyncio.run(
            self._drain_adapter(
                adapter,
                self._turn_context(harness),
                replay_events,
            )
        )

        self.assertTrue(recovered.recovered)
        self.assertEqual(len(client.requests), 1)
        self.assertEqual(
            [event.event_type for event in replay_events],
            ["runtime.output.final", "provider.execution.completed"],
        )
        self.assertEqual(
            replay_events[0].payload["text"],
            "pre-CAS durable answer",
        )

    def test_startup_recovery_materializes_final_events_once(self) -> None:
        harness = HostedAgenticHarness(self)
        client = DeterministicFakeAgenticClient(final_text="startup durable answer")
        adapter = harness.adapter(client)

        def fault(point, _record):
            if point == "committed":
                raise _InjectedProcessCrash(point)

        crashing_journal = ProviderStepJournal(
            store=harness.store,
            fault_hook=fault,
        )
        adapter.loop.provider_step_journal = crashing_journal
        adapter.loop.recovery.journal = crashing_journal
        with self.assertRaises(_InjectedProcessCrash):
            asyncio.run(
                self._drain_adapter(
                    adapter,
                    self._turn_context(harness),
                    [],
                )
            )
        restarted = ProviderStepJournal(store=harness.store)
        adapter.loop.provider_step_journal = restarted
        adapter.loop.recovery.journal = restarted
        context = RuntimeRecoveryContext(
            harness.session,
            harness.binding,
            harness.store.get_provider_state(harness.session.session_id),
            "startup_worker_loss",
        )

        first = asyncio.run(adapter.recover(context))
        terminal = harness.store.list_provider_step_journals(
            session_id=harness.session.session_id
        )[-1]
        revision = terminal.revision
        second = asyncio.run(adapter.recover(context))
        events = harness.store.list_events(harness.session.session_id)

        self.assertTrue(first.recovered)
        self.assertTrue(second.recovered)
        self.assertEqual(len(client.requests), 1)
        self.assertEqual(
            [event.event_type for event in events].count("runtime.output.final"),
            1,
        )
        self.assertEqual(
            [event.event_type for event in events].count(
                "provider.execution.completed"
            ),
            1,
        )
        final_event = next(
            event for event in events if event.event_type == "runtime.output.final"
        )
        self.assertEqual(final_event.payload["text"], "startup durable answer")
        terminal = harness.store.get_provider_step_journal(terminal.journal_id)
        self.assertEqual(terminal.revision, revision)
        self.assertEqual(terminal.final_output_status, "delivered")
        self.assertEqual(terminal.final_completion_status, "delivered")

    def test_undelivered_final_outbox_is_owned_by_original_turn(self) -> None:
        harness = HostedAgenticHarness(self)
        client = DeterministicFakeAgenticClient(final_text="owned durable answer")
        adapter = harness.adapter(client)

        def fault(point, _record):
            if point == "committed":
                raise _InjectedProcessCrash(point)

        crashing_journal = ProviderStepJournal(
            store=harness.store,
            fault_hook=fault,
        )
        adapter.loop.provider_step_journal = crashing_journal
        adapter.loop.recovery.journal = crashing_journal
        with self.assertRaises(_InjectedProcessCrash):
            asyncio.run(
                self._drain_adapter(
                    adapter,
                    self._turn_context(harness),
                    [],
                )
            )

        self.assertEqual(
            provider_step_admission_reason(
                harness.store,
                session_id=harness.session.session_id,
                turn_id="turn-new",
                allow_same_turn_pairing=True,
            ),
            "provider_state_ambiguous",
        )
        self.assertIsNone(
            provider_step_admission_reason(
                harness.store,
                session_id=harness.session.session_id,
                turn_id="turn-hosted",
                allow_same_turn_pairing=True,
            )
        )
        self.assertEqual(len(client.requests), 1)

    def test_missing_final_outbox_identity_quarantines_without_provider_retry(self) -> None:
        harness = HostedAgenticHarness(self)
        client = DeterministicFakeAgenticClient(final_text="unattached answer")
        adapter = harness.adapter(client)
        with patch.object(
            harness.private_state_service,
            "store_final_output",
            side_effect=_InjectedProcessCrash("before_private_outbox"),
        ), self.assertRaises(_InjectedProcessCrash):
            asyncio.run(
                self._drain_adapter(
                    adapter,
                    self._turn_context(harness),
                    [],
                )
            )

        recovered = asyncio.run(
            adapter.recover(
                RuntimeRecoveryContext(
                    harness.session,
                    harness.binding,
                    harness.store.get_provider_state(harness.session.session_id),
                    "missing_final_outbox_restart",
                )
            )
        )

        self.assertFalse(recovered.recovered)
        self.assertEqual(len(client.requests), 1)
        self.assertEqual(
            harness.store.get_session(harness.session.session_id).status,
            "recovery_required",
        )
        terminal = harness.store.list_provider_step_journals(
            session_id=harness.session.session_id
        )[-1]
        self.assertIsNone(terminal.final_output_private_ref)
        self.assertNotIn("unattached answer", repr(terminal))

    @staticmethod
    async def _drain_adapter(adapter, context, target) -> None:
        async for event in adapter.execute(context):
            target.append(event)

    @staticmethod
    def _turn_context(harness) -> RuntimeTurnContext:
        return RuntimeTurnContext(
            session=harness.store.get_session(harness.session.session_id),
            binding=harness.binding,
            provider_state=harness.store.get_provider_state(
                harness.session.session_id
            ),
            input_text="Use only synthetic fixture data.",
            correlation_id="turn-hosted",
            effective_authority=harness.authority,
        )


if __name__ == "__main__":
    unittest.main()
