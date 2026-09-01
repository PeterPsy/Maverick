"""Preliminary tool-ledger resolution and private-WAL regressions."""

from __future__ import annotations

from dataclasses import replace
import unittest

from core.runtime.tool_errors import RuntimeToolError
from core.runtime.tool_ledger import RuntimeToolLedger
from core.runtime.tool_orchestrator import RuntimeToolOrchestrator
from core.runtime.tool_schema import provider_tool_name
from tests.support.cases.tool_orchestrator import (
    _FailOncePrivatePayloadStore,
    _RuntimeToolOrchestratorFixture,
)


class RuntimeToolPreliminaryLedgerTest(
    _RuntimeToolOrchestratorFixture,
    unittest.TestCase,
):
    def test_preliminary_ledger_records_unknown_and_malformed_before_resolution(self) -> None:
        unknown = self.orchestrator.observe_provider_tool(
            provider_tool_name="provider_safe_unknown",
            provider_tool_call_id="call-unknown",
            arguments={"private_secret": "never-public"},
            provider_request_id="request-ledger",
            provider_event_ordinal=7,
            provider_call_index=0,
            authority=self.authority,
            context=self.context,
            turn_id="turn-tools",
            policy=self.policy,
        )
        self.assertEqual(unknown.invocation.state, "proposed")
        self.assertIsNone(unknown.invocation.resolved_tool_handle)
        self.assertNotIn("private_secret", repr(unknown.invocation.arguments_summary))
        self.assertEqual(
            self.ledger.load_arguments(unknown.invocation),
            {"private_secret": "never-public"},
        )
        denied = self.orchestrator.prepare_observed_tool(
            unknown.invocation,
            requested_catalog=self.orchestrator.materialize(
                authority=self.authority,
                context=self.context,
            ),
            authority=self.authority,
            context=self.context,
            policy=self.policy,
        )
        self.assertEqual(denied.invocation.resolution_status, "unknown_tool")
        self.assertIsNotNone(denied.invocation.result_id)

        malformed = self.orchestrator.observe_provider_tool(
            provider_tool_name=provider_tool_name("cli:fixture.read"),
            provider_tool_call_id="call-malformed",
            arguments=b'{"value":',
            provider_request_id="request-ledger",
            provider_event_ordinal=8,
            provider_call_index=1,
            authority=self.authority,
            context=self.context,
            turn_id="turn-tools",
            policy=self.policy,
        )
        malformed = self.orchestrator.prepare_observed_tool(
            malformed.invocation,
            requested_catalog=self.orchestrator.materialize(
                authority=self.authority,
                context=self.context,
            ),
            authority=self.authority,
            context=self.context,
            policy=self.policy,
        )
        self.assertEqual(malformed.invocation.resolution_status, "schema_denied")
        self.assertEqual(
            self.private_store.read(
                workspace_id="default",
                session_id="session-tools",
                private_ref=malformed.invocation.arguments_private_ref,
            ),
            b'{"value":',
        )
        non_finite = self.orchestrator.observe_provider_tool(
            provider_tool_name=provider_tool_name("cli:fixture.read"),
            provider_tool_call_id="call-non-finite",
            arguments={"value": float("nan")},
            provider_request_id="request-ledger",
            provider_event_ordinal=9,
            provider_call_index=2,
            authority=self.authority,
            context=self.context,
            turn_id="turn-tools",
            policy=self.policy,
        )
        non_finite = self.orchestrator.prepare_observed_tool(
            non_finite.invocation,
            requested_catalog=self.orchestrator.materialize(
                authority=self.authority,
                context=self.context,
            ),
            authority=self.authority,
            context=self.context,
            policy=self.policy,
        )
        self.assertEqual(non_finite.invocation.resolution_status, "schema_denied")

    def test_exact_replay_deduplicates_and_divergent_arguments_fail_closed(self) -> None:
        kwargs = dict(
            provider_tool_name=provider_tool_name("cli:fixture.read"),
            provider_tool_call_id="call-replay",
            provider_request_id="request-replay",
            provider_event_ordinal=3,
            provider_call_index=0,
            authority=self.authority,
            context=self.context,
            turn_id="turn-tools",
            policy=self.policy,
        )
        first = self.orchestrator.observe_provider_tool(
            arguments={"value": 1},
            **kwargs,
        )
        replay = self.orchestrator.observe_provider_tool(
            arguments={"value": 1},
            **kwargs,
        )
        self.assertEqual(first.invocation, replay.invocation)
        self.assertEqual(len(self.store.list_tool_invocations(session_id="session-tools")), 1)
        with self.assertRaisesRegex(RuntimeToolError, "replay_mismatch"):
            self.orchestrator.observe_provider_tool(
                arguments={"value": 2},
                **kwargs,
            )

    def test_live_revocation_is_persisted_without_executing(self) -> None:
        requested = self.orchestrator.materialize(
            authority=self.authority,
            context=self.context,
        )
        observed = self.orchestrator.observe_provider_tool(
            provider_tool_name=provider_tool_name("mcp:fixture_mutate"),
            provider_tool_call_id="call-revoked",
            arguments={"value": 1},
            provider_request_id="request-revoked",
            provider_event_ordinal=2,
            provider_call_index=0,
            authority=self.authority,
            context=self.context,
            turn_id="turn-tools",
            policy=self.policy,
        )
        narrowed = self._authority("cli:fixture.read")
        denied = self.orchestrator.prepare_observed_tool(
            observed.invocation,
            requested_catalog=requested,
            authority=narrowed,
            context=self.context,
            policy=self.policy,
        )
        self.assertEqual(denied.invocation.resolution_status, "revoked")
        self.assertEqual(self.mcp_calls, 0)

    def test_live_capability_denial_is_distinct_from_handle_revocation(self) -> None:
        requested = self.orchestrator.materialize(
            authority=self.authority,
            context=self.context,
        )
        observed = self.orchestrator.observe_provider_tool(
            provider_tool_name=provider_tool_name("cli:fixture.read"),
            provider_tool_call_id="call-not-authorized",
            arguments={"value": 1},
            provider_request_id="request-not-authorized",
            provider_event_ordinal=2,
            provider_call_index=0,
            authority=self.authority,
            context=self.context,
            turn_id="turn-tools",
            policy=self.policy,
        )
        narrowed = replace(
            self.authority,
            allowed_capabilities=replace(
                self.authority.allowed_capabilities,
                cli=False,
            ),
        )
        denied = self.orchestrator.prepare_observed_tool(
            observed.invocation,
            requested_catalog=requested,
            authority=narrowed,
            context=self.context,
            policy=self.policy,
        )

        self.assertEqual(denied.invocation.resolution_status, "not_authorized")
        self.assertIsNotNone(denied.invocation.disposition_id)
        self.assertIsNotNone(denied.invocation.result_id)
        self.assertEqual(self.cli_calls, 0)

    def test_preliminary_row_survives_crash_before_private_argument_wal_half(self) -> None:
        private_store = _FailOncePrivatePayloadStore()
        ledger = RuntimeToolLedger(
            store=self.store,
            private_payload_store=private_store,
            digest_key=b"runtime-tool-test-key-32-bytes!!",
        )
        orchestrator = RuntimeToolOrchestrator(
            catalog_builder=self.orchestrator.catalog_builder,
            ledger=ledger,
        )
        arguments = dict(
            provider_tool_name=provider_tool_name("cli:fixture.read"),
            provider_tool_call_id="call-private-wal",
            arguments={"value": 7},
            provider_request_id="request-private-wal",
            provider_event_ordinal=2,
            provider_call_index=0,
            authority=self.authority,
            context=self.context,
            turn_id="turn-tools",
            policy=self.policy,
        )

        with self.assertRaisesRegex(RuntimeToolError, "synthetic_private_store_crash"):
            orchestrator.observe_provider_tool(**arguments)
        preliminary = self.store.find_tool_invocation_by_provider_call(
            session_id="session-tools",
            turn_id="turn-tools",
            provider_tool_call_id="call-private-wal",
        )
        self.assertIsNotNone(preliminary)
        self.assertEqual(preliminary.state, "proposed")

        replay = orchestrator.observe_provider_tool(**arguments)
        self.assertEqual(replay.invocation, preliminary)
        self.assertEqual(ledger.load_arguments(replay.invocation), {"value": 7})



if __name__ == "__main__":
    unittest.main()
