from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Event, Lock, Thread
import tempfile
import unittest
from unittest.mock import patch

from core.api.background_hooks import start_background_hook_scheduler
from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.api.prepared_session_cleanup import run_prepared_session_cleanup_tick
from core.runtime.errors import RuntimeSessionNotFoundError
from core.runtime.service import create_runtime_session, transition_runtime_session
from core.runtime.turn_submission import RuntimeSessionPrewarmResult
from tests.unit.api.app_reference_test_support import AppReferenceApiTestSupport


PENDING_PREWARM = RuntimeSessionPrewarmResult(
    status="pending",
    prewarm_completed=False,
    provider_thread_ready=False,
    runtime_ready=False,
    provider_id="codex",
)


class PreparedRuntimeSessionPoolTestCase(AppReferenceApiTestSupport, unittest.TestCase):
    def test_backend_background_scheduler_starts_periodic_prepared_cleanup(self) -> None:
        state = object()
        shutdown_controller = object()
        with patch(
            "core.api.background_hooks.start_prepared_session_cleanup_scheduler"
        ) as start_cleanup, patch(
            "core.api.background_hooks.start_runtime_session_root_purge_scheduler"
        ) as start_root_purge, patch("core.api.background_hooks.Thread") as thread_type:
            thread = start_background_hook_scheduler(
                state,
                interval_seconds=15,
                shutdown_controller=shutdown_controller,
            )

        start_cleanup.assert_called_once_with(
            state,
            initial_delay_seconds=7.5,
            shutdown_controller=shutdown_controller,
        )
        start_root_purge.assert_called_once_with(
            state,
            initial_delay_seconds=1.0,
            shutdown_controller=shutdown_controller,
        )
        thread_type.return_value.start.assert_called_once_with()
        self.assertIs(thread, thread_type.return_value)

    def test_idle_cleanup_tick_scans_the_session_catalog_once(self) -> None:
        state = object()
        with patch(
            "core.api.prepared_session_cleanup.prepared_session_cleanup_candidates",
            return_value=[],
        ) as candidates:
            result = run_prepared_session_cleanup_tick(state)

        self.assertEqual(result["candidate_count"], 0)
        candidates.assert_called_once()

    def test_repeated_and_concurrent_prepare_requests_create_one_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state, app, cookie = self._platform(temp_dir)
            first_prewarm_entered = Event()
            release_first_prewarm = Event()
            calls_lock = Lock()
            prewarm_calls = 0
            results: list[tuple[int, dict, dict[str, str]] | None] = [None, None]
            errors: list[BaseException] = []

            def delayed_prewarm(*_args, **_kwargs):
                nonlocal prewarm_calls
                with calls_lock:
                    prewarm_calls += 1
                    call_number = prewarm_calls
                if call_number == 1:
                    first_prewarm_entered.set()
                    self.assertTrue(
                        release_first_prewarm.wait(2),
                        "first prepared response was not released",
                    )
                return PENDING_PREWARM

            def invoke(index: int) -> None:
                try:
                    results[index] = self._prepare(app, cookie)
                except BaseException as error:
                    errors.append(error)

            with patch(
                "core.api.runtime_api._prewarm_new_runtime_session",
                side_effect=delayed_prewarm,
            ):
                first = Thread(target=invoke, args=(0,))
                second = Thread(target=invoke, args=(1,))
                first.start()
                self.assertTrue(first_prewarm_entered.wait(2), "first prewarm did not start")
                second.start()
                second.join(2)
                self.assertFalse(second.is_alive(), "reused prepare waited behind the first prewarm")
                release_first_prewarm.set()
                first.join(2)

            if errors:
                raise errors[0]
            payloads = [result[1] for result in results if result is not None]
            self.assertEqual([result[0] for result in results if result is not None], [201, 201])
            self.assertEqual({payload["session_id"] for payload in payloads}, {payloads[0]["session_id"]})
            self.assertEqual(
                sorted(payload["prepared_session_reused"] for payload in payloads),
                [False, True],
            )
            prepared = self._prepared_chat_sessions(state)
            self.assertEqual(len(prepared), 1)
            self.assertIsNotNone(prepared[0].prepared_session_fingerprint)

    def test_pending_after_two_second_wait_reuses_the_same_session_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state, app, cookie = self._platform(temp_dir)
            with patch("core.api.runtime_api.prewarm_runtime_session_async") as start_prewarm, patch(
                "core.api.runtime_api.wait_for_runtime_session_prewarm",
                return_value=False,
            ) as wait_for_prewarm, patch(
                "core.api.runtime_api.runtime_session_prewarm_status",
                return_value=PENDING_PREWARM,
            ):
                first_status, first, _headers = self._prepare(app, cookie)
                second_status, second, _headers = self._prepare(app, cookie)

            self.assertEqual((first_status, second_status), (201, 201))
            self.assertEqual(first["session_id"], second["session_id"])
            self.assertFalse(first["prewarm_completed"])
            self.assertFalse(second["prewarm_completed"])
            self.assertEqual(wait_for_prewarm.call_count, 2)
            self.assertEqual(
                [call.kwargs["timeout_seconds"] for call in wait_for_prewarm.call_args_list],
                [2.0, 2.0],
            )
            self.assertEqual(start_prewarm.call_count, 2)
            self.assertEqual(len(self._prepared_chat_sessions(state)), 1)

    def test_implicit_and_explicit_provider_default_reuse_one_prepared_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state, app, cookie = self._platform(temp_dir)
            with patch(
                "core.api.runtime_api._prewarm_new_runtime_session",
                return_value=PENDING_PREWARM,
            ):
                _status, implicit_default, _headers = self._prepare(app, cookie)
                _status, explicit_default, _headers = self._prepare(
                    app,
                    cookie,
                    reasoning_effort="max",
                )

            self.assertEqual(
                implicit_default["session_id"],
                explicit_default["session_id"],
            )
            self.assertTrue(explicit_default["prepared_session_reused"])
            self.assertEqual(len(self._prepared_chat_sessions(state)), 1)

    def test_discarded_or_aborted_prepare_response_does_not_proliferate_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state, app, cookie = self._platform(temp_dir)
            with patch(
                "core.api.runtime_api._prewarm_new_runtime_session",
                return_value=PENDING_PREWARM,
            ):
                _discarded_response = self._prepare(app, cookie)
                _status, retry, _headers = self._prepare(app, cookie)
                _status, rerender_retry, _headers = self._prepare(app, cookie)

            self.assertEqual(retry["session_id"], rerender_retry["session_id"])
            self.assertTrue(retry["prepared_session_reused"])
            self.assertTrue(rerender_retry["prepared_session_reused"])
            self.assertEqual(len(self._prepared_chat_sessions(state)), 1)

    def test_periodic_cleanup_is_bounded_and_skips_visible_and_inter_agent_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state, app, cookie = self._platform(temp_dir)
            now = datetime.now(tz=UTC)
            prepared_by_project = {}
            with patch(
                "core.api.runtime_api._prewarm_new_runtime_session",
                return_value=PENDING_PREWARM,
            ):
                for index in range(4):
                    _status, payload, _headers = self._prepare(
                        app,
                        cookie,
                        project_id=f"project-{index}",
                    )
                    prepared_by_project[f"project-{index}"] = payload["session_id"]
                visible_status, visible, _headers = self._invoke(
                    app,
                    path="/api/runtime/sessions",
                    method="POST",
                    body={"agent_id": "chat", "source_app_id": "chat", "title": "Visible"},
                    cookie=cookie,
                )
            self.assertEqual(visible_status, 201)

            ages = (31, 3, 2, 1)
            for index, age_minutes in enumerate(ages):
                session_id = prepared_by_project[f"project-{index}"]
                session = state.runtime_store.get_session(session_id)
                state.runtime_store.save_session(
                    replace(session, updated_at=now - timedelta(minutes=age_minutes))
                )
            visible_session = state.runtime_store.get_session(visible["session_id"])
            state.runtime_store.save_session(
                replace(visible_session, updated_at=now - timedelta(hours=2))
            )
            inter_agent = create_runtime_session(
                state.runtime_store,
                session_id="inter-agent-cleanup-proof",
                workspace_id="default",
                agent_id="worker",
                source_app_id="chat",
                owner_user_id="user:admin",
                created_by_user_id="user:admin",
                session_kind="inter_agent_participant",
                thread_visibility="hidden",
                governance=state.workspace_store.get_governance("default"),
                platform_allows_full_access=True,
                now=now - timedelta(hours=2),
                start_path=state.repository_root,
            )
            transition_runtime_session(
                state.runtime_store,
                session_id=inter_agent.session_id,
                target_status="running",
                now=now - timedelta(hours=2),
            )

            result = run_prepared_session_cleanup_tick(
                state,
                now=now,
                ttl_seconds=30 * 60,
                max_per_owner=2,
                max_cleanups=2,
            )

            self.assertEqual(result["attempted"], 2)
            self.assertEqual(
                set(result["cleaned_session_ids"]),
                {
                    prepared_by_project["project-0"],
                    prepared_by_project["project-1"],
                },
            )
            self.assertEqual(len(self._prepared_chat_sessions(state)), 2)
            self.assertEqual(
                state.runtime_store.get_session(visible["session_id"]).thread_visibility,
                "user",
            )
            self.assertEqual(
                state.runtime_store.get_session(inter_agent.session_id).session_kind,
                "inter_agent_participant",
            )
            for deleted_session_id in result["cleaned_session_ids"]:
                with self.assertRaises(RuntimeSessionNotFoundError):
                    state.runtime_store.get_session(deleted_session_id)

    def _platform(self, temp_dir: str):
        repo_root = self._repo_root(temp_dir)
        with patch.dict(
            "os.environ",
            {
                "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                "MAVERICK_ADMIN_USERNAME": "admin",
                "MAVERICK_ADMIN_PASSWORD": "maverick",
            },
        ):
            state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        return state, app, self._login(app)

    def _prepare(
        self,
        app: PlatformHost,
        cookie: str,
        *,
        project_id: str | None = None,
        reasoning_effort: str | None = None,
    ):
        return self._invoke(
            app,
            path="/api/runtime/sessions",
            method="POST",
            body={
                "agent_id": "chat",
                "source_app_id": "chat",
                "prepare_only": True,
                "title": "New chat",
                "skill_activation_mode": "explicit",
                "project_id": project_id,
                "reasoning_effort": reasoning_effort,
            },
            cookie=cookie,
        )

    @staticmethod
    def _prepared_chat_sessions(state):
        return [
            session
            for session in state.runtime_store.list_sessions("default")
            if session.session_kind == "chat_root"
            and session.thread_visibility == "hidden"
            and not state.runtime_store.list_turns(session.session_id)
        ]


if __name__ == "__main__":
    unittest.main()
