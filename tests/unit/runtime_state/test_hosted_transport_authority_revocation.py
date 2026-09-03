from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.providers.agentic_protocol import EphemeralCredential
from core.runtime.execution import execute_runtime_turn
from core.runtime.hosted_agentic_budget import HostedAgenticBudget
from core.runtime.hosted_agentic_models import HostedAgenticLoopError
from tests.support.fake_agentic_provider import DeterministicFakeAgenticClient
from tests.support.hosted_agentic_harness import HostedAgenticHarness


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


class HostedTransportAuthorityRevocationTest(unittest.TestCase):
    def test_live_output_policy_narrowing_during_preflight_blocks_transport(self) -> None:
        harness = HostedAgenticHarness(self)
        live_policy = harness.policy

        def preflight(request, _credential):
            nonlocal live_policy
            self.assertEqual(request.max_output_tokens, 128)
            live_policy = replace(live_policy, max_output_tokens=1)
            return SimpleNamespace(snapshot_digest="8" * 64)

        client = DeterministicFakeAgenticClient()
        events = []
        result = execute_runtime_turn(
            session=harness.session,
            provider=harness.provider,
            input_text="Use only synthetic fixture data.",
            agentic_adapter=harness.adapter(
                client,
                policy_resolver=lambda _context: live_policy,
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
            [{"reason_code": "agent_output_token_limit_reached"}],
        )

    def test_preflight_cannot_consume_active_finalization_deadline_then_open_transport(self) -> None:
        harness = HostedAgenticHarness(self)
        clock = _Clock()

        def budget_factory(policy, finalization_policy, **kwargs):
            return HostedAgenticBudget(
                policy,
                finalization_policy,
                monotonic=clock,
                **kwargs,
            )

        def preflight(_request, _credential):
            clock.value = 4.6
            return SimpleNamespace(snapshot_digest="7" * 64)

        client = DeterministicFakeAgenticClient()
        events = []
        with patch(
            "core.runtime.hosted_agentic_loop.HostedAgenticBudget",
            side_effect=budget_factory,
        ):
            result = execute_runtime_turn(
                session=harness.session,
                provider=harness.provider,
                input_text="Use only synthetic fixture data.",
                agentic_adapter=harness.adapter(
                    client,
                    request_preflight=preflight,
                ),
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
            [{"reason_code": "agent_finalization_time_reserve_reached"}],
        )

    def test_runtime_capability_projection_change_during_preflight_fails_closed(self) -> None:
        harness = HostedAgenticHarness(self)
        live_authority = harness.authority

        def refresh(_context):
            return live_authority

        def preflight(_request, _credential):
            nonlocal live_authority
            live_authority = replace(
                live_authority,
                policy_revision_set=("workspace-live:binding-hosted:1",),
            )
            return SimpleNamespace(snapshot_digest="6" * 64)

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
            [{"reason_code": "runtime_authority_projection_changed"}],
        )

    def test_preflight_credential_rotation_blocks_transport(self) -> None:
        harness = HostedAgenticHarness(self)
        credential_value = "credential-a"
        preflight_values: list[str] = []

        def resolve_credential(_context):
            return EphemeralCredential(credential_value)

        def preflight(_request, credential):
            nonlocal credential_value
            self.assertIsNotNone(credential)
            preflight_values.append(credential.reveal())
            credential_value = "credential-b"
            return SimpleNamespace(snapshot_digest="5" * 64)

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

        self.assertEqual(preflight_values, ["credential-a"])
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(client.requests, [])
        self.assertEqual(
            [event.payload for event in events if event.event_type == "runtime.error"],
            [{"reason_code": "provider_credential_changed_after_preflight"}],
        )
        self.assertNotIn("credential-a", repr(events))
        self.assertNotIn("credential-b", repr(events))

    def test_full_authority_refresh_does_not_run_for_each_provider_event(self) -> None:
        harness = HostedAgenticHarness(self)
        refresh_calls = 0
        revalidation_calls = 0

        def refresh(_context):
            nonlocal refresh_calls
            refresh_calls += 1
            return harness.authority

        def revalidate(_context, authority):
            nonlocal revalidation_calls
            revalidation_calls += 1
            return authority

        client = DeterministicFakeAgenticClient()
        result = execute_runtime_turn(
            session=harness.session,
            provider=harness.provider,
            input_text="Use only synthetic fixture data.",
            agentic_adapter=harness.adapter(
                client,
                authority_refresher=refresh,
                authority_revalidator=revalidate,
                request_preflight=lambda _request, _credential: SimpleNamespace(
                    snapshot_digest="4" * 64
                ),
            ),
            provider_state=harness.store.get_provider_state("session-hosted"),
            correlation_id="turn-hosted",
            effective_authority=harness.authority,
        )

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(refresh_calls, 4)
        self.assertGreaterEqual(revalidation_calls, 1)

    def test_live_data_policy_narrowing_after_lazy_refresh_blocks_transport(self) -> None:
        harness = HostedAgenticHarness(self)
        live_policy = harness.policy
        refresh_calls = 0

        def refresh(_context):
            nonlocal live_policy, refresh_calls
            refresh_calls += 1
            if refresh_calls == 4:
                live_policy = replace(
                    live_policy,
                    allowed_remote_data_classes=(),
                )
            return harness.authority

        client = DeterministicFakeAgenticClient()
        events = []
        result = execute_runtime_turn(
            session=harness.session,
            provider=harness.provider,
            input_text="Use only synthetic fixture data.",
            agentic_adapter=harness.adapter(
                client,
                policy_resolver=lambda _context: live_policy,
                authority_refresher=refresh,
                request_preflight=lambda _request, _credential: SimpleNamespace(
                    snapshot_digest="3" * 64
                ),
            ),
            provider_state=harness.store.get_provider_state("session-hosted"),
            correlation_id="turn-hosted",
            effective_authority=harness.authority,
            event_sink=events.append,
        )

        self.assertEqual(refresh_calls, 4)
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(client.requests, [])
        self.assertEqual(
            [event.payload for event in events if event.event_type == "runtime.error"],
            [{"reason_code": "egress_data_class_denied"}],
        )

    def test_live_catalog_policy_narrowing_after_lazy_refresh_blocks_transport(self) -> None:
        cases = (
            (
                "handle",
                False,
                lambda policy: replace(
                    policy,
                    tool_handle_mode="none",
                    allowed_tool_handles=(),
                ),
                "tool_not_authorized",
            ),
            (
                "surface",
                False,
                lambda policy: replace(policy, allowed_surface_kinds=()),
                "tool_capability_denied",
            ),
            (
                "capability_flag",
                True,
                lambda policy: replace(policy, allow_filesystem_list=False),
                "tool_capability_denied",
            ),
        )
        for name, filesystem_list, narrow, reason_code in cases:
            with self.subTest(name=name):
                harness = HostedAgenticHarness(
                    self,
                    filesystem_list=filesystem_list,
                )
                live_policy = harness.policy
                refresh_calls = 0

                def refresh(_context):
                    nonlocal live_policy, refresh_calls
                    refresh_calls += 1
                    if refresh_calls == 4:
                        live_policy = narrow(live_policy)
                    return harness.authority

                client = DeterministicFakeAgenticClient()
                events = []
                result = execute_runtime_turn(
                    session=harness.session,
                    provider=harness.provider,
                    input_text="Use only synthetic fixture data.",
                    agentic_adapter=harness.adapter(
                        client,
                        policy_resolver=lambda _context: live_policy,
                        authority_refresher=refresh,
                        request_preflight=lambda _request, _credential: SimpleNamespace(
                            snapshot_digest="2" * 64
                        ),
                    ),
                    provider_state=harness.store.get_provider_state("session-hosted"),
                    correlation_id="turn-hosted",
                    effective_authority=harness.authority,
                    event_sink=events.append,
                )

                self.assertEqual(refresh_calls, 4)
                self.assertEqual(result.exit_code, 1)
                self.assertEqual(client.requests, [])
                self.assertEqual(
                    [
                        event.payload
                        for event in events
                        if event.event_type == "runtime.error"
                    ],
                    [{"reason_code": reason_code}],
                )

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
