from __future__ import annotations

import tempfile
import time
from threading import Event, Thread
import unittest
from unittest.mock import patch

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.runtime.turn_submission_service_queue import _queue_turn_with_event
from tests.unit.api.app_reference_test_support import AppReferenceApiTestSupport


class RuntimeSubmitIdempotencyApiTestCase(AppReferenceApiTestSupport, unittest.TestCase):
    def test_new_session_turn_retry_reuses_existing_client_message_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
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
            cookie = self._login(app)
            calls = 0

            def fake_submit_runtime_turn_async(
                submit_state,
                *,
                session,
                input_text,
                client_message_id=None,
                attachments=None,
                app_references=None,
                on_queued=None,
                turn_id=None,
                received_perf_counter=None,
                **_kwargs,
            ):
                nonlocal calls
                calls += 1
                turn, events = _queue_turn_with_event(
                    submit_state,
                    session=session,
                    input_text=input_text,
                    provider_id="codex",
                    client_message_id=client_message_id,
                    attachments=attachments,
                    app_references=app_references,
                    turn_id=turn_id,
                    received_perf_counter=received_perf_counter,
                )
                if on_queued is not None:
                    on_queued(turn, events)
                return turn, events

            body = {
                "agent_id": "chat",
                "source_app_id": "chat",
                "input_text": "retry once",
                "client_message_id": "client-retry",
                "async": True,
            }
            with patch("core.api.runtime_api.submit_runtime_turn_async", side_effect=fake_submit_runtime_turn_async), patch(
                "core.runtime.turn_submission_service_queue.schedule_runtime_thread_title_generation"
            ):
                first_status, first_payload, _headers = self._invoke(
                    app,
                    path="/api/runtime/sessions",
                    method="POST",
                    body=body,
                    cookie=cookie,
                )
                second_status, second_payload, _headers = self._invoke(
                    app,
                    path="/api/runtime/sessions",
                    method="POST",
                    body=body,
                    cookie=cookie,
                )

            self.assertEqual(first_status, 202)
            self.assertEqual(second_status, 200)
            self.assertEqual(calls, 1)
            self.assertEqual(first_payload["session"]["session_id"], second_payload["session"]["session_id"])
            self.assertEqual(first_payload["turn"]["turn_id"], second_payload["turn"]["turn_id"])
            self.assertEqual(first_payload["turn"]["client_message_id"], "client-retry")
            self.assertEqual(len(state.runtime_store.list_sessions("default")), 1)
            metric_events = [
                event
                for event in state.runtime_store.list_events(first_payload["session"]["session_id"])
                if event.event_type == "runtime.turn.receive_to_queued"
            ]
            self.assertEqual(len(metric_events), 1)
            self.assertGreaterEqual(metric_events[0].payload["receive_to_queued_ms"], 0)

    def test_new_session_turn_concurrent_retry_reuses_claimed_turn(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
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
            cookie = self._login(app)
            calls = 0
            first_submit_entered = Event()
            release_queue = Event()

            def fake_submit_runtime_turn_async(
                submit_state,
                *,
                session,
                input_text,
                client_message_id=None,
                attachments=None,
                app_references=None,
                on_queued=None,
                turn_id=None,
                received_perf_counter=None,
                **_kwargs,
            ):
                nonlocal calls
                calls += 1
                first_submit_entered.set()
                self.assertTrue(release_queue.wait(2), "test did not release queue")
                turn, events = _queue_turn_with_event(
                    submit_state,
                    session=session,
                    input_text=input_text,
                    provider_id="codex",
                    client_message_id=client_message_id,
                    attachments=attachments,
                    app_references=app_references,
                    turn_id=turn_id,
                    received_perf_counter=received_perf_counter,
                )
                if on_queued is not None:
                    on_queued(turn, events)
                return turn, events

            body = {
                "agent_id": "chat",
                "source_app_id": "chat",
                "input_text": "retry concurrently",
                "client_message_id": "client-concurrent-retry",
                "async": True,
            }
            results: list[tuple[int, dict] | None] = [None, None]
            errors: list[BaseException] = []

            def invoke(index: int) -> None:
                try:
                    status, payload, _headers = self._invoke(
                        app,
                        path="/api/runtime/sessions",
                        method="POST",
                        body=body,
                        cookie=cookie,
                    )
                    results[index] = (status, payload)
                except BaseException as error:
                    errors.append(error)

            with patch("core.api.runtime_api.submit_runtime_turn_async", side_effect=fake_submit_runtime_turn_async), patch(
                "core.runtime.turn_submission_service_queue.schedule_runtime_thread_title_generation"
            ):
                first = Thread(target=invoke, args=(0,))
                second = Thread(target=invoke, args=(1,))
                first.start()
                self.assertTrue(first_submit_entered.wait(2), "first submit did not enter queue")
                second.start()
                time.sleep(0.05)
                release_queue.set()
                first.join(2)
                second.join(2)

            if errors:
                raise errors[0]
            self.assertTrue(all(result is not None for result in results))
            first_result = results[0]
            second_result = results[1]
            assert first_result is not None
            assert second_result is not None
            self.assertEqual(first_result[0], 202)
            self.assertEqual(second_result[0], 200)
            self.assertEqual(calls, 1)
            self.assertEqual(first_result[1]["session"]["session_id"], second_result[1]["session"]["session_id"])
            self.assertEqual(first_result[1]["turn"]["turn_id"], second_result[1]["turn"]["turn_id"])
            self.assertEqual(len(state.runtime_store.list_sessions("default")), 1)


if __name__ == "__main__":
    unittest.main()
