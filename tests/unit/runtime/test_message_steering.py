from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.providers.errors import ProviderLaunchError
from core.providers.models import RuntimeSteerResult
from core.runtime import message_admission
from core.runtime.message_admission import runtime_message_admission_handoff
from core.runtime.message_steering import attempt_runtime_message_steer
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.runtime_thread import RuntimeThreadRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from tests.support.collections import FakeCollection


class _SteeringAdapter:
    def __init__(self, result: RuntimeSteerResult | None = None) -> None:
        self.result = result or RuntimeSteerResult(status="steered", provider_turn_id="provider-turn-1")
        self.calls: list[dict[str, object]] = []

    def steer_turn(self, session_id: str, **kwargs):
        self.calls.append({"session_id": session_id, **kwargs})
        return self.result


class RuntimeMessageSteeringTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 11, tzinfo=UTC)
        self.store = RuntimeDocumentStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
                client_messages=FakeCollection(),
            )
        )
        self.session = RuntimeSessionRecord(
            session_id="session-1",
            workspace_id="default",
            agent_id="chat",
            status="running",
            requested_mode="sandbox",
            effective_mode="sandbox",
            workspace_root="/workspace",
            workdir="/workspace",
            runtime_root="/runtime",
            started_at=self.now,
            updated_at=self.now,
            ended_at=None,
            last_progress_at=self.now,
            source_app_id="chat",
        )
        self.turn = RuntimeTurnRecord(
            turn_id="turn-1",
            session_id=self.session.session_id,
            workspace_id=self.session.workspace_id,
            status="active",
            input_text="first message",
            created_at=self.now,
            updated_at=self.now,
            started_at=self.now,
            completed_at=None,
            failure_reason=None,
            client_message_id="client-first",
        )
        self.store.save_session(self.session)
        self.store.save_turn(self.turn)
        self.store.save_thread(
            RuntimeThreadRecord(
                thread_id="thread-1",
                workspace_id="default",
                runtime_session_id=self.session.session_id,
                title="First message",
                agent_label="chat",
                agent_type_id="",
                agent_role_id="",
                source_app_id="chat",
                system_prompt="",
                project_id=None,
                archived=False,
                availability="active",
                created_at=self.now,
                updated_at=self.now,
                last_user_message_at=self.now,
                last_completed_response_at=None,
                last_completed_turn_id=None,
            )
        )
        self.store.save_event(
            RuntimeEventRecord(
                event_id="provider-accepted-1",
                workspace_id="default",
                session_id=self.session.session_id,
                plane="turn",
                event_type="runtime.provider.accepted",
                turn_id=self.turn.turn_id,
                process_id=None,
                payload={"provider_id": "codex", "provider_turn_id": "provider-turn-1"},
                created_at=self.now,
            )
        )
        self.state = SimpleNamespace(
            provider_store=object(),
            runtime_store=self.store,
            runtime_event_bus=None,
            runtime_thread_event_bus=None,
        )

    def test_success_is_persisted_and_duplicate_submission_is_idempotent(self) -> None:
        adapter = _SteeringAdapter()
        provider = SimpleNamespace(
            provider_id="codex",
            capabilities=SimpleNamespace(supports_same_turn_input=True),
        )

        with patch(
            "core.runtime.message_steering.resolve_runtime_backend_for_session",
            return_value=(provider, None, adapter),
        ):
            first = self._attempt("client-steer")
            self.store.save_turn(
                replace(
                    self.turn,
                    status="completed",
                    completed_at=self.now,
                    updated_at=self.now,
                )
            )
            duplicate = self._attempt("client-steer")

        self.assertEqual(first.status, "steered")
        self.assertEqual(duplicate.status, "steered")
        self.assertEqual(len(adapter.calls), 1)
        self.assertEqual(adapter.calls[0]["expected_provider_turn_id"], "provider-turn-1")
        self.assertEqual(first.events[0].event_type, "runtime.message.steered")
        claim = self.store.get_client_message_claim(
            workspace_id="default",
            client_message_id="client-steer",
        )
        self.assertIsNotNone(claim)
        self.assertEqual(claim.status, "steered")

    def test_successful_skill_steers_persist_the_union_on_the_active_turn(self) -> None:
        adapter = _SteeringAdapter()
        provider = SimpleNamespace(
            provider_id="codex",
            capabilities=SimpleNamespace(supports_same_turn_input=True),
        )
        first_skill = SimpleNamespace(skill_id="storage-ops")
        second_skill = SimpleNamespace(skill_id="review-ops")

        with patch(
            "core.runtime.message_steering.resolve_runtime_backend_for_session",
            return_value=(provider, None, adapter),
        ), patch(
            "core.runtime.message_steering.resolve_invoked_runtime_skills",
            side_effect=([first_skill], [second_skill]),
        ):
            first = attempt_runtime_message_steer(
                self.state,
                session=self.session,
                input_text="store the report",
                client_message_id="client-skill-steer-1",
                invoked_skill_ids=["storage-ops"],
            )
            second = attempt_runtime_message_steer(
                self.state,
                session=self.session,
                input_text="review the report",
                client_message_id="client-skill-steer-2",
                invoked_skill_ids=["review-ops"],
            )

        persisted = self.store.get_turn(self.turn.turn_id)
        self.assertEqual(first.status, "steered")
        self.assertEqual(second.status, "steered")
        self.assertEqual(persisted.invoked_skill_ids, ["storage-ops", "review-ops"])
        self.assertEqual(second.events[0].payload["invoked_skill_ids"], ["review-ops"])

    def test_skill_steer_falls_back_to_a_new_turn_when_the_active_turn_has_32_skills(self) -> None:
        adapter = _SteeringAdapter()
        provider = SimpleNamespace(
            provider_id="codex",
            capabilities=SimpleNamespace(supports_same_turn_input=True),
        )
        self.store.merge_turn_invoked_skill_ids(
            turn_id=self.turn.turn_id,
            invoked_skill_ids=[f"existing-skill-{index}" for index in range(32)],
        )

        with patch(
            "core.runtime.message_steering.resolve_runtime_backend_for_session",
            return_value=(provider, None, adapter),
        ), patch(
            "core.runtime.message_steering.resolve_invoked_runtime_skills",
            return_value=[SimpleNamespace(skill_id="new-skill")],
        ):
            result = attempt_runtime_message_steer(
                self.state,
                session=self.session,
                input_text="invoke one more skill",
                client_message_id="client-skill-overflow",
                invoked_skill_ids=["new-skill"],
            )

        self.assertEqual(result.status, "fallback")
        self.assertEqual(result.reason, "too_many_invoked_skills")
        self.assertEqual(adapter.calls, [])

    def test_uncertain_delivery_is_terminal_and_never_retried(self) -> None:
        adapter = _SteeringAdapter(
            RuntimeSteerResult(status="delivery_uncertain", provider_turn_id="provider-turn-1", reason="timeout")
        )
        provider = SimpleNamespace(
            provider_id="codex",
            capabilities=SimpleNamespace(supports_same_turn_input=True),
        )

        with patch(
            "core.runtime.message_steering.resolve_runtime_backend_for_session",
            return_value=(provider, None, adapter),
        ):
            first = self._attempt("client-uncertain")
            duplicate = self._attempt("client-uncertain")

        self.assertEqual(first.status, "delivery_uncertain")
        self.assertEqual(duplicate.status, "delivery_uncertain")
        self.assertEqual(len(adapter.calls), 1)
        claim = self.store.get_client_message_claim(
            workspace_id="default",
            client_message_id="client-uncertain",
        )
        self.assertIsNotNone(claim)
        self.assertEqual(claim.status, "delivery_uncertain")

    def test_provider_without_same_turn_input_falls_back_without_reserving_the_message(self) -> None:
        adapter = _SteeringAdapter()
        provider = SimpleNamespace(
            provider_id="hosted",
            capabilities=SimpleNamespace(supports_same_turn_input=False),
        )

        with patch(
            "core.runtime.message_steering.resolve_runtime_backend_for_session",
            return_value=(provider, None, adapter),
        ):
            result = self._attempt("client-fallback")

        self.assertEqual(result.status, "fallback")
        self.assertEqual(result.reason, "provider_does_not_support_same_turn_input")
        self.assertEqual(adapter.calls, [])
        self.assertIsNone(
            self.store.get_client_message_claim(
                workspace_id="default",
                client_message_id="client-fallback",
            )
        )

    def test_existing_queued_turn_prevents_overtaking_by_a_later_steer(self) -> None:
        adapter = _SteeringAdapter()
        provider = SimpleNamespace(
            provider_id="codex",
            capabilities=SimpleNamespace(supports_same_turn_input=True),
        )
        self.store.save_turn(
            RuntimeTurnRecord(
                turn_id="turn-queued-before-steer",
                session_id=self.session.session_id,
                workspace_id=self.session.workspace_id,
                status="queued",
                input_text="already next",
                created_at=self.now,
                updated_at=self.now,
                started_at=None,
                completed_at=None,
                failure_reason=None,
                client_message_id="client-already-next",
            )
        )

        with patch(
            "core.runtime.message_steering.resolve_runtime_backend_for_session",
            return_value=(provider, None, adapter),
        ):
            result = self._attempt("client-must-follow-queue")

        self.assertEqual(result.status, "fallback")
        self.assertEqual(result.reason, "runtime_turn_queue_not_empty")
        self.assertEqual(adapter.calls, [])

    def test_plain_hosted_runtime_falls_back_before_provider_resolution(self) -> None:
        plain_session = replace(self.session, runtime_mode="plain_hosted_chat")

        with patch("core.runtime.message_steering.resolve_runtime_backend_for_session") as resolve_backend:
            result = attempt_runtime_message_steer(
                self.state,
                session=plain_session,
                input_text="additional direction",
                client_message_id="client-plain",
            )

        self.assertEqual(result.status, "fallback")
        self.assertEqual(result.reason, "runtime_mode_does_not_support_same_turn_input")
        resolve_backend.assert_not_called()

    def test_unexpected_adapter_failure_remains_delivery_uncertain(self) -> None:
        adapter = _SteeringAdapter()
        provider = SimpleNamespace(
            provider_id="codex",
            capabilities=SimpleNamespace(supports_same_turn_input=True),
        )

        with patch(
            "core.runtime.message_steering.resolve_runtime_backend_for_session",
            return_value=(provider, None, adapter),
        ), patch.object(adapter, "steer_turn", side_effect=RuntimeError("adapter crashed")):
            result = self._attempt("client-adapter-error")

        self.assertEqual(result.status, "delivery_uncertain")
        claim = self.store.get_client_message_claim(
            workspace_id="default",
            client_message_id="client-adapter-error",
        )
        self.assertIsNotNone(claim)
        self.assertEqual(claim.status, "delivery_uncertain")

    def test_provider_input_preparation_failure_releases_claim_for_queue_fallback(self) -> None:
        adapter = _SteeringAdapter()
        provider = SimpleNamespace(
            provider_id="codex",
            capabilities=SimpleNamespace(supports_same_turn_input=True),
        )

        with patch(
            "core.runtime.message_steering.resolve_runtime_backend_for_session",
            return_value=(provider, None, adapter),
        ), patch.object(
            adapter,
            "steer_turn",
            side_effect=ProviderLaunchError("invoked_skill_runtime_path_missing"),
        ):
            result = self._attempt("client-provider-input-failed")

        self.assertEqual(result.status, "fallback")
        self.assertEqual(result.reason, "provider_input_not_dispatched")
        self.assertIsNone(
            self.store.get_client_message_claim(
                workspace_id="default",
                client_message_id="client-provider-input-failed",
            )
        )

    def test_admission_registry_reuses_nested_lock_and_releases_idle_session(self) -> None:
        session_id = "session-admission-cleanup"

        with runtime_message_admission_handoff(session_id):
            entry = message_admission._MESSAGE_ADMISSION_LOCKS[session_id]
            self.assertEqual(entry.users, 1)
            with runtime_message_admission_handoff(session_id):
                self.assertIs(message_admission._MESSAGE_ADMISSION_LOCKS[session_id], entry)
                self.assertEqual(entry.users, 2)
            self.assertEqual(entry.users, 1)

        self.assertNotIn(session_id, message_admission._MESSAGE_ADMISSION_LOCKS)

    def _attempt(self, client_message_id: str):
        return attempt_runtime_message_steer(
            self.state,
            session=self.session,
            input_text="additional direction",
            client_message_id=client_message_id,
        )


if __name__ == "__main__":
    unittest.main()
