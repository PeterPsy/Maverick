from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.providers.agentic_models import codex_routing_constraint, codex_runtime_policy
from core.providers.service import builtin_provider_registry
from core.providers.certificate_service import runtime_adapter_artifact_digest
from core.runtime.execution_binding import build_runtime_execution_binding
from core.runtime.service import create_runtime_session, transition_runtime_session
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.runtime.turn_submission import (
    prewarm_runtime_session_async,
    runtime_session_prewarm_status,
    submit_runtime_turn_async,
)
from tests.support.collections import FakeCollection
from tests.support.fake_agentic_adapter import FakeHostedAgenticAdapter
from tests.support.agentic_certification import (
    certified_test_provider_store,
    fake_capability_evidence,
)
from tests.support.repo import make_temp_repo_root


class AgenticTurnSubmissionTest(unittest.TestCase):
    def test_common_lifecycle_executes_non_process_adapter_without_launch_spec(self) -> None:
        repo_root = make_temp_repo_root(self)
        runtime_store = RuntimeDocumentStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
                provider_states=FakeCollection(),
            )
        )
        timestamp = datetime(2026, 8, 16, tzinfo=UTC)
        adapter = FakeHostedAgenticAdapter(output_text="common lifecycle answer")
        evidence = fake_capability_evidence(adapter, now=timestamp)
        binding = build_runtime_execution_binding(
            session_id="session-fake-hosted",
            workspace_id="default",
            profile_definition_id="profile-fake-hosted",
            profile_definition_revision="1",
            workspace_binding_id="binding-fake-hosted",
            workspace_binding_revision=0,
            capability_certificate_id="certificate-fake-hosted",
            runtime_engine_id="fake-hosted-agentic",
            adapter_id="fake-hosted-agentic-adapter",
            adapter_version="1",
            adapter_artifact_digest=runtime_adapter_artifact_digest(adapter),
            model_provider_id="fake-model-provider",
            model_id="fake-model-v1",
            provider_protocol="fake-stream-v1",
            provider_api_version="v1",
            routing_constraint=codex_routing_constraint(),
            credential_binding_id=None,
            reasoning_effort=None,
            certified_reasoning_efforts=(),
            default_reasoning_effort=None,
            execution_mode="sandbox",
            profile_policy_ceiling=codex_runtime_policy(),
            workspace_policy_ceiling=codex_runtime_policy(),
            egress_policy_id="fake-only",
            egress_policy_revision="1",
            created_at=timestamp,
            certificate_evidence_digest=evidence.evidence_digest,
        )
        session = create_runtime_session(
            runtime_store,
            session_id=binding.session_id,
            workspace_id=binding.workspace_id,
            agent_id="chat",
            execution_binding=binding,
            now=timestamp,
            start_path=repo_root,
        )
        session = transition_runtime_session(
            runtime_store,
            session_id=session.session_id,
            target_status="running",
            now=timestamp,
        )
        provider_store = certified_test_provider_store(
            binding,
            adapter,
            evidence=evidence,
            now=timestamp,
            validity_days=30,
        )
        definition = replace(
            builtin_provider_registry().get_provider_definition("codex"),
            provider_id=adapter.runtime_engine_id,
            label="Fake hosted agentic",
        )
        state = SimpleNamespace(
            provider_store=provider_store,
            runtime_store=runtime_store,
            runtime_event_bus=None,
            runtime_thread_event_bus=None,
            repository_root=repo_root,
        )

        with patch.dict(
            submit_runtime_turn_async.__globals__,
            {
                "Thread": _ImmediateThread,
                "Timer": _DiscardedTimer,
                "resolve_runtime_engine_for_session": Mock(
                    return_value=(definition, None, adapter, None)
                ),
                "_build_launch_spec_for_execution": Mock(
                    side_effect=AssertionError("non-process adapter requested a launch spec")
                ),
                "release_idle_runtime_processes": Mock(return_value=0),
            },
        ), patch("core.runtime.turn_submission_service_queue.schedule_runtime_thread_title_generation"):
            prewarm_runtime_session_async(state, session=session)
            prewarm = runtime_session_prewarm_status(session.session_id)
            turn, _events = submit_runtime_turn_async(state, session=session, input_text="hello")

        self.assertEqual(runtime_store.get_turn(turn.turn_id).status, "completed")
        self.assertTrue(prewarm.prewarm_completed)
        self.assertTrue(prewarm.runtime_ready)
        self.assertFalse(prewarm.provider_thread_ready)
        self.assertEqual(adapter.prepare_calls, 2)
        self.assertEqual(adapter.execute_calls, 1)
        self.assertEqual(
            runtime_store.get_provider_state(session.session_id).continuation_id,
            "fake-continuation",
        )
        event_types = [event.event_type for event in runtime_store.list_events(session.session_id)]
        self.assertIn("runtime.output.final", event_types)
        self.assertIn("runtime.authority.prewarm_evaluated", event_types)
        self.assertIn("runtime.authority.evaluated", event_types)
        authority_event = next(
            event for event in runtime_store.list_events(session.session_id)
            if event.event_type == "runtime.authority.evaluated"
        )
        self.assertEqual(len(authority_event.payload["authority_digest"]), 64)
        self.assertNotIn("allowed_tool_handles", authority_event.payload)


class _ImmediateThread:
    def __init__(self, *, target, name, daemon) -> None:
        self.target = target

    def start(self) -> None:
        self.target()


class _DiscardedTimer:
    def __init__(self, _delay, _target) -> None:
        self.daemon = False

    def start(self) -> None:
        return None


if __name__ == "__main__":
    unittest.main()
