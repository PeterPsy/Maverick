"""Provider-step correlation regressions for the Phase-0 inventory."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import unittest

from core.providers.agentic_models import codex_routing_constraint, codex_runtime_policy
from core.runtime.agentic_inventory import inventory_remote_agentic_sessions
from core.runtime.agentic_inventory_steps import correlate_provider_steps
from core.runtime.execution_binding import build_runtime_execution_binding
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.runtime.tool_models import ToolInvocationRecord
from tests.support.collections import FakeCollection


NOW = datetime(2026, 8, 25, 20, 0, tzinfo=UTC)
TURN_ID = "turn-remote"


class RemoteAgenticInventoryTest(unittest.TestCase):
    def test_four_tool_steps_plus_final_response_have_no_gap(self) -> None:
        events: list[RuntimeEventRecord] = []
        invocations: list[ToolInvocationRecord] = []
        for step in range(1, 6):
            events.extend(self._provider_step_events(step))
            if step < 5:
                invocation = self._invocation(f"invocation-{step}", seconds=step * 10 + 2)
                invocations.append(invocation)
                events.append(
                    self._event(
                        f"proposal-{step}",
                        "runtime.tool_call.proposed",
                        {"invocation_id": invocation.invocation_id},
                        seconds=step * 10 + 3,
                    )
                )
            else:
                events.append(
                    self._event(
                        "final-5",
                        "runtime.output.final",
                        {"text": "done"},
                        seconds=step * 10 + 3,
                    )
                )

        correlation = correlate_provider_steps(events, invocations)

        self.assertEqual(correlation.request_count, 5)
        self.assertEqual(correlation.acceptance_count, 5)
        self.assertEqual(len(correlation.persisted_proposal_ids), 4)
        self.assertEqual(correlation.ambiguous_step_count, 0)
        self.assertEqual(correlation.unaccounted_acceptance_count, 0)

    def test_step_without_final_or_persisted_proposal_is_ambiguous(self) -> None:
        correlation = correlate_provider_steps(self._provider_step_events(1), [])

        self.assertEqual(correlation.ambiguous_step_count, 1)
        self.assertEqual(correlation.unaccounted_acceptance_count, 1)

    def test_request_and_acceptance_without_ids_pair_by_event_order(self) -> None:
        events = [
            self._event("sent-anonymous", "runtime.provider.turn_start_sent", {}, seconds=10),
            self._event("accepted-anonymous", "runtime.provider.accepted", {}, seconds=11),
            self._event("final-anonymous", "runtime.output.final", {"text": "done"}, seconds=12),
        ]

        correlation = correlate_provider_steps(events, [])

        self.assertEqual(correlation.request_count, 1)
        self.assertEqual(correlation.acceptance_count, 1)
        self.assertEqual(correlation.ambiguous_step_count, 0)

    def test_multiple_proposals_are_correlated_to_their_distinct_steps(self) -> None:
        first = self._invocation("invocation-1a", seconds=12)
        second = self._invocation("invocation-1b", seconds=13)
        third = self._invocation("invocation-2", seconds=22)
        events = [
            *self._provider_step_events(1),
            self._event("proposal-1a", "runtime.tool_call.proposed", {"invocation_id": first.invocation_id}, seconds=14),
            self._event("proposal-1b", "runtime.tool_call.proposed", {"invocation_id": second.invocation_id}, seconds=15),
            *self._provider_step_events(2),
            self._event("proposal-2", "runtime.tool_call.proposed", {"invocation_id": third.invocation_id}, seconds=24),
            *self._provider_step_events(3),
            self._event("final-3", "runtime.output.final", {"text": "done"}, seconds=34),
        ]

        correlation = correlate_provider_steps(events, [first, second, third])

        self.assertEqual(correlation.persisted_proposal_ids, (
            "invocation-1a",
            "invocation-1b",
            "invocation-2",
        ))
        self.assertEqual(correlation.ambiguous_step_count, 0)

    def test_archive_pagination_preserves_step_order_across_page_boundary(self) -> None:
        store = self._store()
        session = self._remote_session()
        store.insert_session(session)
        store.save_turn(
            RuntimeTurnRecord(
                turn_id=TURN_ID,
                session_id=session.session_id,
                workspace_id=session.workspace_id,
                status="completed",
                input_text="redacted",
                created_at=NOW,
                updated_at=NOW,
                started_at=NOW,
                completed_at=NOW,
                failure_reason=None,
            )
        )
        invocation = self._invocation("invocation-paged", seconds=600)
        proposed = store.initialize_tool_invocation(
            replace(
                invocation,
                state="proposed",
                result_private_ref=None,
                result_summary=None,
                revision=0,
            )
        )
        store.update_tool_invocation(invocation, expected_revision=proposed.revision)
        for event in self._provider_step_events(1):
            store.save_event(event)
        for index in range(500):
            store.save_event(
                self._event(
                    f"noise-{index}",
                    "runtime.step.updated",
                    {"index": index},
                    seconds=2 + index,
                )
            )
        store.save_event(
            self._event(
                "proposal-paged",
                "runtime.tool_call.proposed",
                {"invocation_id": invocation.invocation_id},
                seconds=601,
            )
        )
        for event in self._provider_step_events(2, base_seconds=610):
            store.save_event(event)
        store.save_event(
            self._event(
                "final-paged",
                "runtime.output.final",
                {"text": "done"},
                seconds=613,
            )
        )

        item = inventory_remote_agentic_sessions(store)[0]

        self.assertEqual(item.provider_request_count, 2)
        self.assertEqual(item.provider_acceptance_count, 2)
        self.assertEqual(item.ledger_proposal_count, 1)
        self.assertEqual(item.ambiguous_provider_step_count, 0)
        self.assertNotIn("provider_step_outcome_ambiguous", item.reason_codes)

    def _provider_step_events(
        self,
        step: int,
        *,
        base_seconds: int | None = None,
    ) -> list[RuntimeEventRecord]:
        base = step * 10 if base_seconds is None else base_seconds
        request_id = f"provider-request-{step}"
        return [
            self._event(
                f"sent-{step}-{base}",
                "runtime.provider.turn_start_sent",
                {"request_id": request_id},
                seconds=base,
            ),
            self._event(
                f"accepted-{step}-{base}",
                "runtime.provider.accepted",
                {"request_id": request_id},
                seconds=base + 1,
            ),
        ]

    @staticmethod
    def _event(
        event_id: str,
        event_type: str,
        payload: dict[str, object],
        *,
        seconds: int,
    ) -> RuntimeEventRecord:
        return RuntimeEventRecord(
            event_id=event_id,
            workspace_id="default",
            session_id="session-remote",
            plane="turn",
            event_type=event_type,
            turn_id=TURN_ID,
            process_id=None,
            payload=payload,
            created_at=NOW + timedelta(seconds=seconds),
        )

    @staticmethod
    def _invocation(invocation_id: str, *, seconds: int) -> ToolInvocationRecord:
        timestamp = NOW + timedelta(seconds=seconds)
        return ToolInvocationRecord(
            invocation_id=invocation_id,
            workspace_id="default",
            session_id="session-remote",
            turn_id=TURN_ID,
            provider_tool_call_id=f"provider-{invocation_id}",
            resolved_tool_handle="core-capability:filesystem.read",
            arguments_private_ref=f"private:{invocation_id}",
            arguments_summary={"field_count": 1},
            arguments_digest="a" * 64,
            idempotency_key=(invocation_id[-1] * 64)[:64],
            effect_class="read",
            state="succeeded",
            policy_revision="1",
            authority_digest="b" * 64,
            confirmation_grant_id=None,
            result_private_ref=f"private:result:{invocation_id}",
            result_summary={"field_count": 1},
            failure_reason=None,
            revision=1,
            created_at=timestamp,
            updated_at=timestamp,
        )

    @staticmethod
    def _store() -> RuntimeDocumentStore:
        return RuntimeDocumentStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
                provider_states=FakeCollection(),
                tool_invocations=FakeCollection(),
            )
        )

    @staticmethod
    def _remote_session() -> RuntimeSessionRecord:
        policy = codex_runtime_policy()
        binding = build_runtime_execution_binding(
            session_id="session-remote",
            workspace_id="default",
            profile_definition_id="profile-remote",
            profile_definition_revision="1",
            workspace_binding_id="binding-remote",
            workspace_binding_revision=1,
            capability_certificate_id="certificate-remote",
            certificate_evidence_digest="c" * 64,
            runtime_engine_id="maverick-tool-loop",
            adapter_id="hosted-adapter",
            adapter_version="5",
            adapter_artifact_digest="d" * 64,
            model_provider_id="google-ai-studio",
            model_id="gemini-test",
            provider_protocol="google-interactions",
            provider_api_version="v1",
            routing_constraint=codex_routing_constraint(),
            credential_binding_id=None,
            reasoning_effort=None,
            certified_reasoning_efforts=(),
            default_reasoning_effort=None,
            execution_mode="sandbox",
            profile_policy_ceiling=policy,
            workspace_policy_ceiling=policy,
            egress_policy_id="remote-contained",
            egress_policy_revision="1",
            created_at=NOW,
        )
        return RuntimeSessionRecord(
            session_id=binding.session_id,
            workspace_id=binding.workspace_id,
            agent_id="chat",
            status="stopped",
            requested_mode="sandbox",
            effective_mode="sandbox",
            workspace_root="/workspace",
            workdir="/workspace",
            runtime_root="/runtime/session-remote",
            started_at=NOW,
            updated_at=NOW,
            ended_at=NOW,
            last_progress_at=NOW,
            execution_binding=binding,
            provider_id=binding.runtime_engine_id,
        )


if __name__ == "__main__":
    unittest.main()
