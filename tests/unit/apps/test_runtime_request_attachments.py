from __future__ import annotations

from pathlib import Path
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import core.apps.runtime_requests as runtime_requests
import core.runtime.turn_submission_service_runtime as runtime_submission_runtime
from core.runtime.execution import RuntimeExecutionResult
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.runtime.turn_submission_service_queue import _queue_turn_with_event
from core.workspaces.service import default_workspace_governance
from tests.support.collections import FakeCollection
from tests.support.repo import make_temp_repo_root


APP_ID = "sensor-hub"


class RuntimeRequestAttachmentsTestCase(unittest.TestCase):
    def _runtime_store(self) -> RuntimeDocumentStore:
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

    def _runtime_request_parsed(self, *, create_sessions: bool = True) -> SimpleNamespace:
        return SimpleNamespace(
            contract=SimpleNamespace(
                permissions=SimpleNamespace(runtime=SimpleNamespace(create_sessions=create_sessions)),
                capabilities=SimpleNamespace(data_events=[]),
            )
        )

    def _runtime_request_state(self) -> SimpleNamespace:
        return SimpleNamespace(
            app_store=SimpleNamespace(),
            provider_store=SimpleNamespace(),
            runtime_store=self._runtime_store(),
            runtime_event_bus=None,
            app_event_bus=None,
            observability_store=None,
            workspace_store=SimpleNamespace(
                get_governance=lambda workspace_id: default_workspace_governance(workspace_id)
            ),
        )

    def _write_generated_storage_file(self, repo_root: Path) -> str:
        relative_path = "storage/generated/sensor-hub/device-1/frame.jpg"
        path = repo_root / "workspaces" / "default" / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"frame")
        return relative_path

    def test_accepts_valid_storage_attachment(self) -> None:
        repo_root = make_temp_repo_root(self)
        relative_path = self._write_generated_storage_file(repo_root)

        attachments = runtime_requests._validated_runtime_request_attachments(
            [
                {
                    "id": "cap_1",
                    "name": "device-frame.jpg",
                    "workspace_relative_path": relative_path,
                    "content_type": "image/jpeg",
                    "size_bytes": 5,
                    "ignored": "client-only",
                }
            ],
            workspace_id="default",
            start_path=repo_root,
        )

        self.assertEqual(attachments, [self._expected_attachment(relative_path)])

    def test_rejects_invalid_attachments(self) -> None:
        repo_root = make_temp_repo_root(self)
        valid_path = self._write_generated_storage_file(repo_root)
        cases = [
            ({"relative_path": valid_path}, "must be a list"),
            (["not an object"], "must be an object"),
            ([{"relative_path": "/storage/generated/frame.jpg"}], "workspace-relative"),
            ([{"relative_path": "storage/generated/../frame.jpg"}], "workspace-relative"),
            ([{"relative_path": "data/sensor-hub/frame.jpg"}], "under storage/uploaded or storage/generated"),
            ([{"relative_path": "storage/generated/missing.jpg"}], "was not found"),
            ([{"relative_path": valid_path, "size_bytes": "5"}], "size_bytes must be numeric"),
            ([{"relative_path": valid_path, "size_bytes": -1}], "non-negative integer"),
            ([{"relative_path": valid_path} for _ in range(runtime_requests.MAX_RUNTIME_REQUEST_ATTACHMENTS + 1)], "at most"),
        ]
        for value, pattern in cases:
            with self.subTest(pattern=pattern):
                with self.assertRaisesRegex(runtime_requests.AppHostingError, pattern):
                    runtime_requests._validated_runtime_request_attachments(
                        value,
                        workspace_id="default",
                        start_path=repo_root,
                    )

    def test_passes_storage_attachments_to_queued_turn(self) -> None:
        repo_root = make_temp_repo_root(self)
        relative_path = self._write_generated_storage_file(repo_root)
        state = self._runtime_request_state()
        state.repository_root = repo_root
        result = {
            "json": {"ok": True},
            "runtime_launch_requests": [
                {
                    "request_id": "capture-1",
                    "agent_id": "chat",
                    "agent_label": "Maverick",
                    "title": "Device visual input",
                    "input_text": "Inspect this device frame.",
                    "attachments": [self._attachment_request(relative_path)],
                }
            ],
        }
        captured: dict[str, object] = {}

        def fake_submit_runtime_turn_async(
            submit_state,
            *,
            session,
            input_text,
            client_message_id=None,
            attachments=None,
            app_references=None,
            invoked_skill_ids=None,
            on_queued=None,
        ):
            captured["attachments"] = attachments
            turn, events = _queue_turn_with_event(
                submit_state,
                session=session,
                input_text=input_text,
                provider_id="test-provider",
                client_message_id=client_message_id,
                attachments=attachments,
                app_references=app_references,
            )
            if on_queued is not None:
                on_queued(turn, events)
            return turn, events

        with (
            patch.object(runtime_requests, "_authorize_new_agentic_app_session", return_value=(object(), object())),
            patch.object(runtime_requests, "effective_provider_registry", return_value=object()),
            patch.object(runtime_requests, "build_pinned_execution_binding", return_value=None),
            patch.object(runtime_requests, "_require_exact_authorized_binding_pin"),
            patch.object(runtime_requests, "runtime_skill_catalog_app_id_for_request", lambda *_args, **_kwargs: None),
            patch.object(runtime_requests, "submit_runtime_turn_async", fake_submit_runtime_turn_async),
        ):
            runtime_results = runtime_requests.apply_app_runtime_requests(
                state,
                result=result,
                workspace_id="default",
                app_id=APP_ID,
                source_root=Path(f"/apps/{APP_ID}"),
                backend_entrypoint=None,
                data_root=f"workspaces/default/data/{APP_ID}",
                parsed=self._runtime_request_parsed(),
                start_path=repo_root,
            )

        expected_attachment = self._expected_attachment(relative_path)
        session_id = runtime_results[0]["runtime_session_id"]
        queued_event = next(event for event in state.runtime_store.list_events(session_id) if event.event_type == "runtime.turn.queued")

        self.assertEqual(runtime_results[0]["status"], "submitted")
        self.assertEqual(captured["attachments"], [expected_attachment])
        self.assertEqual(state.runtime_store.get_session(session_id).source_app_id, APP_ID)
        self.assertEqual(state.runtime_store.get_thread(session_id).source_app_id, APP_ID)
        self.assertEqual(queued_event.payload["attachments"], [expected_attachment])

    def test_runtime_request_materializes_storage_attachment_link_for_provider(self) -> None:
        repo_root = make_temp_repo_root(self)
        relative_path = self._write_generated_storage_file(repo_root)
        state = self._runtime_request_state()
        state.repository_root = repo_root
        result = {
            "json": {"ok": True},
            "runtime_launch_requests": [
                {
                    "request_id": "capture-1",
                    "agent_id": "chat",
                    "agent_label": "Maverick",
                    "title": "Device visual input",
                    "input_text": "Inspect this device frame.",
                    "attachments": [self._attachment_request(relative_path)],
                }
            ],
        }
        captured: dict[str, object] = {}
        executed = Event()
        completed = Event()

        def fake_resolve_runtime_engine_for_session(_provider_store, *, session, **_kwargs):
            return (
                SimpleNamespace(provider_id="test-provider"),
                SimpleNamespace(),
                SimpleNamespace(local_process_lifecycle=object()),
                SimpleNamespace(),
            )

        def fake_execute_runtime_turn(**kwargs):
            captured["input_text"] = kwargs["input_text"]
            executed.set()
            return RuntimeExecutionResult(output_text="done", exit_code=0)

        def fake_dispatch_source_app_runtime_event(*_args, **_kwargs):
            completed.set()

        with (
            patch.object(runtime_requests, "_authorize_new_agentic_app_session", return_value=(object(), object())),
            patch.object(runtime_requests, "effective_provider_registry", return_value=object()),
            patch.object(runtime_requests, "build_pinned_execution_binding", return_value=None),
            patch.object(runtime_requests, "_require_exact_authorized_binding_pin"),
            patch.object(runtime_requests, "runtime_skill_catalog_app_id_for_request", lambda *_args, **_kwargs: None),
            patch.object(runtime_submission_runtime, "resolve_runtime_engine_for_session", fake_resolve_runtime_engine_for_session),
            patch.object(runtime_submission_runtime, "_build_launch_spec_for_execution", lambda *_args, **_kwargs: None),
            patch.object(runtime_submission_runtime, "execute_runtime_turn", fake_execute_runtime_turn),
            patch.object(runtime_submission_runtime, "dispatch_source_app_runtime_event", fake_dispatch_source_app_runtime_event),
            patch.object(runtime_submission_runtime, "release_idle_runtime_processes", lambda *_args, **_kwargs: 0),
        ):
            runtime_results = runtime_requests.apply_app_runtime_requests(
                state,
                result=result,
                workspace_id="default",
                app_id=APP_ID,
                source_root=Path(f"/apps/{APP_ID}"),
                backend_entrypoint=None,
                data_root=f"workspaces/default/data/{APP_ID}",
                parsed=self._runtime_request_parsed(),
                start_path=repo_root,
            )
            self.assertTrue(executed.wait(2), "runtime worker did not execute")
            self.assertTrue(completed.wait(2), "runtime worker did not complete")

        session_id = runtime_results[0]["runtime_session_id"]
        turn_id = runtime_results[0]["turn_id"]
        provider_input = captured["input_text"]
        self.assertEqual(runtime_results[0]["status"], "submitted")
        self.assertEqual(state.runtime_store.get_turn(turn_id).status, "completed")
        self.assertIsInstance(provider_input, str)
        self.assertIn("Inspect this device frame.", provider_input)
        self.assertIn("Uploaded attachments:", provider_input)
        self.assertIn("device-frame.jpg", provider_input)
        self.assertIn("image/jpeg", provider_input)
        self.assertIn(relative_path, provider_input)
        self.assertIn(str(repo_root / "workspaces" / "default" / relative_path), provider_input)
        self.assertEqual(state.runtime_store.get_session(session_id).source_app_id, APP_ID)

    def test_runtime_launch_requests_require_declared_create_sessions_permission(self) -> None:
        result = {
            "json": {"ok": True},
            "runtime_launch_requests": [{"request_id": "request-1", "agent_id": "chat", "input_text": "Hello"}],
        }

        with self.assertRaisesRegex(runtime_requests.AppHostingError, "without declaring runtime.create_sessions"):
            runtime_requests.apply_app_runtime_requests(
                SimpleNamespace(),
                result=result,
                workspace_id="default",
                app_id=APP_ID,
                source_root=Path(f"/apps/{APP_ID}"),
                backend_entrypoint=None,
                data_root=f"workspaces/default/data/{APP_ID}",
                parsed=self._runtime_request_parsed(create_sessions=False),
                start_path=Path(__file__).resolve().parents[3],
            )

    def _attachment_request(self, relative_path: str) -> dict[str, object]:
        return {
            "id": "cap_1",
            "name": "device-frame.jpg",
            "relative_path": relative_path,
            "content_type": "image/jpeg",
            "size_bytes": 5,
        }

    def _expected_attachment(self, relative_path: str) -> dict[str, object]:
        return {
            "relative_path": relative_path,
            "workspace_relative_path": relative_path,
            "id": "cap_1",
            "name": "device-frame.jpg",
            "content_type": "image/jpeg",
            "size_bytes": 5,
        }


if __name__ == "__main__":
    unittest.main()
