from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.providers.models import ProviderSelection, RuntimeBackendLaunchSpec
from core.providers.provider_codex import build_codex_definition
from core.runtime.service import create_runtime_session, queue_runtime_turn
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.runtime.turn_submission import prewarm_runtime_session_async, submit_runtime_turn_async
from core.runtime.turn_submission_launch_cache import clear_cached_runtime_launch_context
from core.runtime.turn_submission_service_output import _build_launch_spec_for_execution
from tests.support.collections import FakeCollection
from tests.support.repo import make_temp_repo_root


class TurnSubmissionLaunchSpecTestCase(unittest.TestCase):
    def test_prewarm_accepts_brand_new_session(self) -> None:
        repo_root = make_temp_repo_root(self)
        runtime_store = _runtime_store()
        session = create_runtime_session(
            runtime_store,
            session_id="sess-no-first-prewarm",
            workspace_id="default",
            agent_id="agent-1",
            start_path=repo_root,
        )
        state = SimpleNamespace(runtime_store=runtime_store, provider_store=SimpleNamespace())

        with patch("core.runtime.turn_submission_service_runtime.Thread") as thread:
            prewarm_runtime_session_async(state, session=session)

        thread.assert_called_once()

    def test_completed_async_turn_schedules_prewarm_for_next_turn(self) -> None:
        repo_root = make_temp_repo_root(self)
        runtime_store = _runtime_store()
        session = create_runtime_session(
            runtime_store,
            session_id="sess-prewarm-after-turn",
            workspace_id="default",
            agent_id="agent-1",
            start_path=repo_root,
        )
        adapter = _FakeRuntimeAdapter()
        provider = build_codex_definition()
        launch_spec = _launch_spec(session)
        scheduled_timers: list[_CapturingTimer] = []
        prewarm = Mock()
        state = SimpleNamespace(
            provider_store=SimpleNamespace(),
            runtime_store=runtime_store,
            runtime_event_bus=None,
            runtime_thread_event_bus=None,
            repository_root=repo_root,
        )

        with patch.dict(
            submit_runtime_turn_async.__globals__,
            {
                "Thread": _ImmediateThread,
                "Timer": lambda delay, target: _CapturingTimer(delay, target, scheduled_timers),
                "resolve_runtime_backend_for_session": Mock(return_value=(provider, None, adapter)),
                "_build_launch_spec_for_execution": Mock(return_value=(launch_spec, {})),
                "execute_runtime_turn": Mock(return_value=SimpleNamespace(output_text="done", exit_code=0)),
                "release_idle_runtime_processes": Mock(return_value=0),
                "prewarm_runtime_session_async": prewarm,
            },
        ), patch("core.runtime.turn_submission_service_queue.schedule_runtime_thread_title_generation"):
            turn, _events = submit_runtime_turn_async(state, session=session, input_text="hello")

            self.assertEqual(runtime_store.get_turn(turn.turn_id).status, "completed")
            self.assertEqual(len(scheduled_timers), 1)
            self.assertGreaterEqual(scheduled_timers[0].delay, 0)
            scheduled_timers[0].target()

        prewarm.assert_called_once()
        self.assertEqual(prewarm.call_args.kwargs["session"].session_id, session.session_id)

    def test_prewarm_runs_with_queued_turn_before_execution(self) -> None:
        repo_root = make_temp_repo_root(self)
        runtime_store = _runtime_store()
        session = create_runtime_session(
            runtime_store,
            session_id="sess-prewarm-with-queued-turn",
            workspace_id="default",
            agent_id="agent-1",
            start_path=repo_root,
        )
        queue_runtime_turn(runtime_store, turn_id="turn-queued", session_id=session.session_id, input_text="hello")
        provider = build_codex_definition()
        adapter = _FakeRuntimeAdapter()
        launch_spec = _launch_spec(session)
        state = SimpleNamespace(
            provider_store=SimpleNamespace(),
            runtime_store=runtime_store,
            runtime_event_bus=None,
            repository_root=repo_root,
        )

        with patch("core.runtime.turn_submission_service_runtime.Thread", _ImmediateThread), patch(
            "core.runtime.turn_submission_service_runtime.resolve_runtime_backend_for_session",
            Mock(return_value=(provider, None, adapter)),
        ), patch(
            "core.runtime.turn_submission_service_runtime._build_launch_spec_for_execution",
            Mock(return_value=(launch_spec, {})),
        ), patch(
            "core.providers.codex_app_server.prewarm_codex_app_server_runtime",
            Mock(return_value="provider-thread-queued"),
        ) as prewarm_runtime:
            prewarm_runtime_session_async(state, session=session)

        prewarm_runtime.assert_called_once()
        updated = runtime_store.get_session(session.session_id)
        self.assertEqual(updated.provider_thread_id, "provider-thread-queued")

    def test_async_worker_waits_for_session_prewarm_before_execution(self) -> None:
        repo_root = make_temp_repo_root(self)
        runtime_store = _runtime_store()
        session = create_runtime_session(
            runtime_store,
            session_id="sess-wait-for-prewarm",
            workspace_id="default",
            agent_id="agent-1",
            start_path=repo_root,
        )
        adapter = _FakeRuntimeAdapter()
        provider = build_codex_definition()
        launch_spec = _launch_spec(session)
        calls: list[str] = []
        state = SimpleNamespace(
            provider_store=SimpleNamespace(),
            runtime_store=runtime_store,
            runtime_event_bus=None,
            runtime_thread_event_bus=None,
            repository_root=repo_root,
        )

        def wait_for_prewarm(session_id: str) -> bool:
            calls.append(f"wait:{session_id}")
            return True

        def execute_turn(**_kwargs):
            calls.append("execute")
            return SimpleNamespace(output_text="done", exit_code=0)

        with patch.dict(
            submit_runtime_turn_async.__globals__,
            {
                "Thread": _ImmediateThread,
                "_wait_for_session_prewarm": wait_for_prewarm,
                "resolve_runtime_backend_for_session": Mock(return_value=(provider, None, adapter)),
                "_build_launch_spec_for_execution": Mock(return_value=(launch_spec, {})),
                "execute_runtime_turn": execute_turn,
                "release_idle_runtime_processes": Mock(return_value=0),
            },
        ), patch("core.runtime.turn_submission_service_queue.schedule_runtime_thread_title_generation"):
            turn, _events = submit_runtime_turn_async(state, session=session, input_text="hello")

        self.assertEqual(runtime_store.get_turn(turn.turn_id).status, "completed")
        self.assertEqual(calls[:2], [f"wait:{session.session_id}", "execute"])

    def test_execution_launch_spec_uses_resolved_runtime_adapter(self) -> None:
        repo_root = make_temp_repo_root(self)
        runtime_store = _runtime_store()
        session = create_runtime_session(
            runtime_store,
            session_id="sess-resolved-launch",
            workspace_id="default",
            agent_id="agent-1",
            start_path=repo_root,
        )
        adapter = _FakeRuntimeAdapter()
        selection = ProviderSelection(
            selection_id="default:runtime",
            workspace_id="default",
            provider_id="codex",
            binding_id=None,
            selection_scope="workspace_default",
            selection_reason="test",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            model_id="gpt-test",
            model_reasoning_effort="low",
        )
        state = SimpleNamespace(
            provider_store=SimpleNamespace(),
            runtime_store=runtime_store,
            secret_store=None,
            observability_store=None,
            repository_root=repo_root,
        )

        with patch(
            "core.runtime.turn_submission_service_output.build_runtime_backend_launch_spec",
            side_effect=AssertionError("provider resolution should not run twice"),
        ):
            spec, metadata = _build_launch_spec_for_execution(
                state,
                session=session,
                provider_id="codex",
                provider_definition=build_codex_definition(),
                provider_selection=selection,
                runtime_adapter=adapter,
            )

        self.assertEqual(spec.provider_id, "codex")
        self.assertEqual(adapter.launch_calls, [("gpt-test", "low")])
        self.assertEqual(adapter.skill_prepare_calls, [[]])
        self.assertEqual(metadata["provider_id_resolved"], "codex")
        self.assertFalse(metadata["launch_cache_hit"])

    def test_execution_launch_spec_reuses_cached_codex_launch_context(self) -> None:
        repo_root = make_temp_repo_root(self)
        runtime_store = _runtime_store()
        session = create_runtime_session(
            runtime_store,
            session_id="sess-cached-launch",
            workspace_id="default",
            agent_id="agent-1",
            start_path=repo_root,
        )
        adapter = _FakeRuntimeAdapter()
        state = SimpleNamespace(
            provider_store=SimpleNamespace(),
            runtime_store=runtime_store,
            secret_store=None,
            observability_store=None,
            repository_root=repo_root,
        )
        clear_cached_runtime_launch_context(session.session_id)

        first_spec, first_metadata = _build_launch_spec_for_execution(
            state,
            session=session,
            provider_id="codex",
            provider_definition=build_codex_definition(),
            provider_selection=None,
            runtime_adapter=adapter,
        )
        second_spec, second_metadata = _build_launch_spec_for_execution(
            state,
            session=session,
            provider_id="codex",
            provider_definition=build_codex_definition(),
            provider_selection=None,
            runtime_adapter=adapter,
        )

        self.assertIs(first_spec, second_spec)
        self.assertEqual(adapter.launch_calls, [(None, None)])
        self.assertEqual(adapter.skill_prepare_calls, [[]])
        self.assertFalse(first_metadata["launch_cache_hit"])
        self.assertTrue(second_metadata["launch_cache_hit"])
        self.assertEqual(second_metadata["launch_spec_ms"], 0.0)
        self.assertEqual(second_metadata["skill_resolve_ms"], 0.0)
        self.assertEqual(second_metadata["skill_prepare_ms"], 0.0)


class _FakeRuntimeAdapter:
    def __init__(self) -> None:
        self.launch_calls: list[tuple[str | None, str | None]] = []
        self.skill_prepare_calls: list[list[str]] = []

    def build_launch_spec(
        self,
        session,
        *,
        secret_env=None,
        credential_binding_id=None,
        resolved_secret_refs=None,
        model_id=None,
        model_reasoning_effort=None,
    ) -> RuntimeBackendLaunchSpec:
        self.launch_calls.append((model_id, model_reasoning_effort))
        return RuntimeBackendLaunchSpec(
            provider_id="codex",
            command=["/bin/echo"],
            env_overrides={},
            credential_binding_id=credential_binding_id,
            resolved_secret_refs=resolved_secret_refs or [],
            working_directory=session.workdir,
            execution_mode=session.effective_mode,
            readable_roots=[],
            writable_roots=[],
        )

    def prepare_runtime_skills(self, _session, skills):
        self.skill_prepare_calls.append([skill.skill_id for skill in skills])
        return []


class _ImmediateThread:
    def __init__(self, *, target, name, daemon) -> None:
        self.target = target

    def start(self) -> None:
        self.target()


class _CapturingTimer:
    def __init__(self, delay: float, target, sink: list["_CapturingTimer"]) -> None:
        self.delay = delay
        self.target = target
        self.daemon = False
        sink.append(self)

    def start(self) -> None:
        return None


def _launch_spec(session) -> RuntimeBackendLaunchSpec:
    return RuntimeBackendLaunchSpec(
        provider_id="codex",
        command=["/bin/echo"],
        env_overrides={},
        credential_binding_id=None,
        resolved_secret_refs=[],
        working_directory=session.workdir,
        execution_mode=session.effective_mode,
        readable_roots=[],
        writable_roots=[],
    )


def _runtime_store() -> RuntimeDocumentStore:
    return RuntimeDocumentStore(
        RuntimeCollections(
            sessions=FakeCollection(),
            turns=FakeCollection(),
            events=FakeCollection(),
            processes=FakeCollection(),
            states=FakeCollection(),
            threads=FakeCollection(),
        )
    )


if __name__ == "__main__":
    unittest.main()
