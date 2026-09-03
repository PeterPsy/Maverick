from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.providers.agentic_protocol import EphemeralCredential
from core.runtime.execution import execute_runtime_turn
from core.runtime.hosted_agentic_models import HostedAgenticLoopError
from tests.support.fake_agentic_provider import DeterministicFakeAgenticClient
from tests.support.hosted_agentic_harness import HostedAgenticHarness


class HostedTransportAuthorityRevocationTest(unittest.TestCase):
    def test_live_egress_policy_narrowing_during_preflight_blocks_transport(self) -> None:
        harness = HostedAgenticHarness(self)
        remote_data_allowed = True

        def refresh(_context):
            if remote_data_allowed:
                return harness.authority
            return replace(
                harness.authority,
                allowed_remote_data_classes=(),
            )

        def preflight(_request, _credential):
            nonlocal remote_data_allowed
            remote_data_allowed = False
            return SimpleNamespace(snapshot_digest="9" * 64)

        client = DeterministicFakeAgenticClient()
        events = []
        result = execute_runtime_turn(
            session=harness.session,
            provider=harness.provider,
            input_text="Use only synthetic fixture data.",
            agentic_adapter=harness.adapter(
                client,
                authority_refresher=refresh,
                request_preflight=preflight,
            ),
            provider_state=harness.store.get_provider_state("session-hosted"),
            correlation_id="turn-hosted",
            effective_authority=harness.authority,
            event_sink=events.append,
        )

        self.assertEqual(result.exit_code, 1)
        self.assertEqual(client.requests, [])
        self.assertEqual(
            [event.payload for event in events if event.event_type == "runtime.error"],
            [{"reason_code": "egress_data_class_denied"}],
        )

    def test_full_authority_revocation_during_preflight_blocks_transport(self) -> None:
        harness = HostedAgenticHarness(self)
        binding_live = True
        refresh_calls = 0

        def refresh(_context):
            nonlocal refresh_calls
            refresh_calls += 1
            if not binding_live:
                raise HostedAgenticLoopError(
                    "workspace_profile_binding_disabled"
                )
            return harness.authority

        def preflight(_request, _credential):
            nonlocal binding_live
            binding_live = False
            return SimpleNamespace(snapshot_digest="a" * 64)

        client = DeterministicFakeAgenticClient()
        events = []
        result = execute_runtime_turn(
            session=harness.session,
            provider=harness.provider,
            input_text="Use only synthetic fixture data.",
            agentic_adapter=harness.adapter(
                client,
                authority_refresher=refresh,
                request_preflight=preflight,
            ),
            provider_state=harness.store.get_provider_state("session-hosted"),
            correlation_id="turn-hosted",
            effective_authority=harness.authority,
            event_sink=events.append,
        )

        self.assertEqual(result.exit_code, 1)
        self.assertEqual(client.requests, [])
        self.assertGreaterEqual(refresh_calls, 3)
        self.assertEqual(
            [event.payload for event in events if event.event_type == "runtime.error"],
            [{"reason_code": "workspace_profile_binding_disabled"}],
        )

    def test_full_authority_revocation_after_journal_blocks_lazy_transport(self) -> None:
        harness = HostedAgenticHarness(self)
        certificate_live = True
        refresh_calls = 0

        def refresh(_context):
            nonlocal refresh_calls
            refresh_calls += 1
            if not certificate_live:
                raise HostedAgenticLoopError("certificate_revoked")
            return harness.authority

        client = DeterministicFakeAgenticClient()
        adapter = harness.adapter(
            client,
            authority_refresher=refresh,
            request_preflight=lambda _request, _credential: SimpleNamespace(
                snapshot_digest="b" * 64
            ),
        )
        journal_request = adapter.loop.provider_step_journal.journal_request

        def revoke_after_journal(record):
            nonlocal certificate_live
            saved = journal_request(record)
            certificate_live = False
            return saved

        events = []
        with patch.object(
            adapter.loop.provider_step_journal,
            "journal_request",
            side_effect=revoke_after_journal,
        ):
            result = execute_runtime_turn(
                session=harness.session,
                provider=harness.provider,
                input_text="Use only synthetic fixture data.",
                agentic_adapter=adapter,
                provider_state=harness.store.get_provider_state(
                    "session-hosted"
                ),
                correlation_id="turn-hosted",
                effective_authority=harness.authority,
                event_sink=events.append,
            )

        self.assertEqual(result.exit_code, 1)
        self.assertEqual(client.requests, [])
        self.assertGreaterEqual(refresh_calls, 4)
        self.assertEqual(
            [event.payload for event in events if event.event_type == "runtime.error"],
            [{"reason_code": "certificate_revoked"}],
        )

    def test_credential_revocation_during_preflight_blocks_transport(self) -> None:
        harness = HostedAgenticHarness(self)
        credential_live = True
        credential_calls = 0

        def resolve_credential(_context):
            nonlocal credential_calls
            credential_calls += 1
            if not credential_live:
                return None
            return EphemeralCredential("fixture-secret")

        def preflight(_request, _credential):
            nonlocal credential_live
            credential_live = False
            return SimpleNamespace(snapshot_digest="c" * 64)

        client = DeterministicFakeAgenticClient()
        events = []
        result = execute_runtime_turn(
            session=harness.session,
            provider=harness.provider,
            input_text="Use only synthetic fixture data.",
            agentic_adapter=harness.adapter(
                client,
                credential_resolver=resolve_credential,
                credential_required=True,
                request_preflight=preflight,
            ),
            provider_state=harness.store.get_provider_state("session-hosted"),
            correlation_id="turn-hosted",
            effective_authority=harness.authority,
            event_sink=events.append,
        )

        self.assertEqual(result.exit_code, 1)
        self.assertEqual(client.requests, [])
        self.assertGreaterEqual(credential_calls, 2)
        self.assertEqual(
            [event.payload for event in events if event.event_type == "runtime.error"],
            [{"reason_code": "provider_credential_authorization_missing"}],
        )

    def test_credential_revocation_after_journal_blocks_lazy_transport(self) -> None:
        harness = HostedAgenticHarness(self)
        credential_live = True

        def resolve_credential(_context):
            return (
                EphemeralCredential("fixture-secret")
                if credential_live
                else None
            )

        client = DeterministicFakeAgenticClient()
        adapter = harness.adapter(
            client,
            credential_resolver=resolve_credential,
            credential_required=True,
            request_preflight=lambda _request, _credential: SimpleNamespace(
                snapshot_digest="d" * 64
            ),
        )
        journal_request = adapter.loop.provider_step_journal.journal_request

        def revoke_after_journal(record):
            nonlocal credential_live
            saved = journal_request(record)
            credential_live = False
            return saved

        events = []
        with patch.object(
            adapter.loop.provider_step_journal,
            "journal_request",
            side_effect=revoke_after_journal,
        ):
            result = execute_runtime_turn(
                session=harness.session,
                provider=harness.provider,
                input_text="Use only synthetic fixture data.",
                agentic_adapter=adapter,
                provider_state=harness.store.get_provider_state(
                    "session-hosted"
                ),
                correlation_id="turn-hosted",
                effective_authority=harness.authority,
                event_sink=events.append,
            )

        self.assertEqual(result.exit_code, 1)
        self.assertEqual(client.requests, [])
        self.assertEqual(
            [event.payload for event in events if event.event_type == "runtime.error"],
            [{"reason_code": "provider_credential_authorization_missing"}],
        )


if __name__ == "__main__":
    unittest.main()
