from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import core.apps.runtime_requests as runtime_requests
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.service import create_runtime_session
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from tests.support.collections import FakeCollection
from tests.support.repo import make_temp_repo_root


class RuntimeRequestsTestCase(unittest.TestCase):
    def _state(self) -> SimpleNamespace:
        return SimpleNamespace(
            app_store=SimpleNamespace(
                get_workspace_app_binding=lambda **_kwargs: SimpleNamespace(data_root="workspaces/default/data/storage")
            ),
            secret_store=None,
            observability_store=None,
            workspace_store=None,
        )

    def _provider_parsed(self, *, backend: str | None = "backend/app_backend.py", read_secrets: list[str] | None = None) -> SimpleNamespace:
        return SimpleNamespace(
            contract=SimpleNamespace(
                entrypoints=SimpleNamespace(backend=backend),
                permissions=SimpleNamespace(secrets=SimpleNamespace(read=read_secrets or [])),
            )
        )

    def _resolved_dependencies(self, *, surfaces: list[str] | None = None) -> dict[str, object]:
        return {
            "status": "resolved",
            "dependencies": [
                {
                    "alias": "storage-local-path",
                    "status": "resolved",
                    "selected_provider_app_ids": ["storage"],
                    "candidates": [{"app_id": "storage", "surfaces": surfaces or ["backend"]}],
                }
            ],
        }

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

    def test_dependency_backend_invocation_passes_trusted_context(self) -> None:
        captured_payloads: list[dict[str, object]] = []

        def fake_resolve_dependencies(*_args, **_kwargs):
            return self._resolved_dependencies()

        def fake_resolve_surface(*_args, **_kwargs):
            return Path("/provider/storage"), self._provider_parsed()

        def fake_run_entrypoint(_entrypoint, *, payload, **_kwargs):
            captured_payloads.append(payload)
            if payload.get("surface") == "secret_selector":
                return {"requires_secrets": False}
            return {"status_code": 200, "json": {"ok": True}}

        def fake_secret_delivery(*_args, **_kwargs):
            return SimpleNamespace(secrets={}, errors=[])

        with (
            patch.object(runtime_requests, "resolve_app_dependencies", fake_resolve_dependencies),
            patch.object(runtime_requests, "resolve_workspace_app_surface", fake_resolve_surface),
            patch.object(runtime_requests, "run_json_entrypoint", fake_run_entrypoint),
            patch.object(runtime_requests, "resolve_app_secret_payload_requests", fake_secret_delivery),
        ):
            result = runtime_requests._invoke_dependency_backend(
                self._state(),
                workspace_id="default",
                app_id="video-studio",
                dependency_alias="storage-local-path",
                body={"action": "file.local_path.resolve"},
                start_path=Path(__file__).resolve().parents[3],
            )

        payload = captured_payloads[-1]
        self.assertEqual(result["json"], {"ok": True})
        self.assertEqual(result["dependency_provider_app_id"], "storage")
        self.assertEqual(payload["surface"], "dependency_backend")
        self.assertEqual(payload["effective_mode"], "full-access")
        self.assertEqual(payload["app_id"], "storage")
        self.assertEqual(payload["consumer_app_id"], "video-studio")
        self.assertEqual(payload["dependency_alias"], "storage-local-path")
        self.assertTrue(str(payload["uploaded_storage_root"]).endswith("workspaces/default/storage/uploaded"))
        self.assertTrue(str(payload["generated_storage_root"]).endswith("workspaces/default/storage/generated"))

    def test_dependency_backend_passes_speech_provider_config(self) -> None:
        captured_payloads: list[dict[str, object]] = []
        speech_status = {
            "profile": "speech_stt",
            "credential_binding": {
                "binding_id": "binding-deepgram",
                "provider_id": "deepgram",
                "workspace_id": "default",
                "label": "Deepgram",
                "status": "active",
                "created_at": datetime(2026, 1, 1, tzinfo=UTC),
                "updated_at": datetime(2026, 1, 2, tzinfo=UTC),
            },
            "selection": {
                "provider_id": "deepgram",
                "audio_transcription_model_id": "nova-3",
                "conversation_model_id": "flux-general-multi",
            },
            "model_settings": {
                "audio_transcription_model_id": "nova-3",
                "conversation_model_id": "flux-general-multi",
            },
        }

        def fake_resolve_dependencies(*_args, **_kwargs):
            return {
                "status": "resolved",
                "dependencies": [
                    {
                        "alias": "speech-to-text",
                        "interface": "speech.transcription",
                        "status": "resolved",
                        "selected_provider_app_ids": ["speech"],
                        "candidates": [{"app_id": "speech", "surfaces": ["backend"]}],
                    }
                ],
            }

        def fake_resolve_surface(*_args, **_kwargs):
            return Path("/provider/speech"), self._provider_parsed(read_secrets=["deepgram-api-key"])

        def fake_run_entrypoint(_entrypoint, *, payload, **_kwargs):
            json.dumps(payload, ensure_ascii=True)
            captured_payloads.append(payload)
            if payload.get("surface") == "secret_selector":
                return {"requires_secrets": False}
            return {"status_code": 200, "json": {"ok": True}}

        def fake_secret_delivery(*_args, **_kwargs):
            return SimpleNamespace(secrets={"deepgram-api-key": "token"}, errors=[])

        with (
            patch.object(runtime_requests, "resolve_app_dependencies", fake_resolve_dependencies),
            patch.object(runtime_requests, "resolve_workspace_app_surface", fake_resolve_surface),
            patch.object(runtime_requests, "run_json_entrypoint", fake_run_entrypoint),
            patch.object(runtime_requests, "resolve_app_secret_payload_requests", fake_secret_delivery),
            patch("core.api.provider_api.workspace_speech_stt_status", return_value=speech_status),
        ):
            result = runtime_requests._invoke_dependency_backend(
                self._state(),
                workspace_id="default",
                app_id="chat",
                dependency_alias="speech-to-text",
                body={"action": "transcribe_audio"},
                start_path=Path(__file__).resolve().parents[3],
            )

        payload = captured_payloads[-1]
        self.assertEqual(result["json"], {"ok": True})
        self.assertEqual(payload["app_id"], "speech")
        self.assertEqual(
            payload["provider_config"],
            {
                "speech_stt": {
                    "audio_transcription_model_id": "nova-3",
                    "conversation_model_id": "flux-general-multi",
                }
            },
        )

    def test_dependency_backend_requires_selected_provider_backend_surface(self) -> None:
        def fake_resolve_dependencies(*_args, **_kwargs):
            return self._resolved_dependencies(surfaces=["mcp"])

        with patch.object(runtime_requests, "resolve_app_dependencies", fake_resolve_dependencies):
            with self.assertRaisesRegex(runtime_requests.AppHostingError, "does not declare backend surface"):
                runtime_requests._invoke_dependency_backend(
                    self._state(),
                    workspace_id="default",
                    app_id="video-studio",
                    dependency_alias="storage-local-path",
                    body={"action": "file.local_path.resolve"},
                    start_path=Path(__file__).resolve().parents[3],
                )

    def test_dependency_backend_uses_provider_secret_selector_for_drive_locator(self) -> None:
        captured_requests: dict[str, object] = {}

        def fake_resolve_dependencies(*_args, **_kwargs):
            return self._resolved_dependencies()

        def fake_resolve_surface(*_args, **_kwargs):
            return Path("/provider/storage"), self._provider_parsed(
                read_secrets=[
                    "google-drive-oauth-client-id",
                    "google-drive-oauth-client-secret",
                    "google-drive-refresh-token",
                ]
            )

        def fake_run_entrypoint(_entrypoint, *, payload, **_kwargs):
            if payload.get("surface") == "secret_selector":
                self.assertEqual(payload["body"]["stable_storage_file_id"], "file_drive")
                return {
                    "requires_secrets": True,
                    "secret_requests": [
                        {"logical_names": ["google-drive-oauth-client-id", "google-drive-oauth-client-secret"]},
                        {
                            "logical_names": ["google-drive-refresh-token"],
                            "resource_type": "drive_connection",
                            "resource_id": "drive_conn_abc",
                        },
                    ],
                }
            return {"status_code": 200, "json": {"local_path": "/tmp/storage/file.bin"}}

        def fake_secret_delivery(*_args, **kwargs):
            captured_requests["requests"] = kwargs["requests"]
            captured_requests["fail_closed"] = kwargs["fail_closed"]
            return SimpleNamespace(
                secrets={
                    "google-drive-oauth-client-id": "client-id",
                    "google-drive-oauth-client-secret": "client-secret",
                    "google-drive-refresh-token": "refresh-token",
                },
                errors=[],
            )

        with (
            patch.object(runtime_requests, "resolve_app_dependencies", fake_resolve_dependencies),
            patch.object(runtime_requests, "resolve_workspace_app_surface", fake_resolve_surface),
            patch.object(runtime_requests, "run_json_entrypoint", fake_run_entrypoint),
            patch.object(runtime_requests, "resolve_app_secret_payload_requests", fake_secret_delivery),
        ):
            result = runtime_requests._invoke_dependency_backend(
                self._state(),
                workspace_id="default",
                app_id="video-studio",
                dependency_alias="storage-local-path",
                body={"action": "file.local_path.resolve", "stable_storage_file_id": "file_drive"},
                start_path=Path(__file__).resolve().parents[3],
            )

        requests = captured_requests["requests"]
        self.assertEqual(result["json"], {"local_path": "/tmp/storage/file.bin"})
        self.assertTrue(captured_requests["fail_closed"])
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0].logical_names, ["google-drive-oauth-client-id", "google-drive-oauth-client-secret"])
        self.assertIsNone(requests[0].resource_type)
        self.assertEqual(requests[1].logical_names, ["google-drive-refresh-token"])
        self.assertEqual(requests[1].resource_type, "drive_connection")
        self.assertEqual(requests[1].resource_id, "drive_conn_abc")

    def test_apply_app_runtime_requests_handles_dependency_backend_requests(self) -> None:
        result = {
            "json": {"ok": True},
            "dependency_backend_requests": [
                {
                    "request_id": "resolve-local-path",
                    "dependency_alias": "storage-local-path",
                    "body": {"action": "file.local_path.resolve", "stable_storage_file_id": "file_drive"},
                }
            ],
        }
        parsed = SimpleNamespace(
            contract=SimpleNamespace(
                permissions=SimpleNamespace(runtime=SimpleNamespace(create_sessions=False)),
                capabilities=SimpleNamespace(data_events=[]),
            )
        )

        def fake_invoke_dependency_backend(*_args, **_kwargs):
            return {
                "status_code": 200,
                "dependency_provider_app_id": "storage",
                "json": {"local_path": "/tmp/storage/file.bin"},
            }

        with patch.object(runtime_requests, "_invoke_dependency_backend", fake_invoke_dependency_backend):
            runtime_results = runtime_requests.apply_app_runtime_requests(
                SimpleNamespace(),
                result=result,
                workspace_id="default",
                app_id="video-studio",
                source_root=Path("/apps/video-studio"),
                backend_entrypoint=None,
                data_root="workspaces/default/data/video-studio",
                parsed=parsed,
                start_path=Path(__file__).resolve().parents[3],
            )

        self.assertEqual(runtime_results, [])
        self.assertEqual(
            result["json"]["dependency_backend_request_results"],
            [
                {
                    "request_id": "resolve-local-path",
                    "dependency_alias": "storage-local-path",
                    "provider_app_id": "storage",
                    "status": "completed",
                    "status_code": 200,
                    "callback_status_code": 0,
                }
            ],
        )

    def test_app_runtime_requests_reject_hidden_inter_agent_sessions(self) -> None:
        runtime_store = self._runtime_store()
        now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
        repo_root = make_temp_repo_root(self)
        create_runtime_session(
            runtime_store,
            session_id="hidden-child",
            workspace_id="default",
            agent_id="child-agent",
            source_app_id="video-studio",
            session_kind="inter_agent_participant",
            thread_visibility="hidden",
            start_path=repo_root,
        )
        runtime_store.save_turn(
            RuntimeTurnRecord(
                turn_id="hidden-turn",
                session_id="hidden-child",
                workspace_id="default",
                status="active",
                input_text="work",
                created_at=now,
                updated_at=now,
                started_at=now,
                completed_at=None,
                failure_reason=None,
            )
        )
        state = SimpleNamespace(runtime_store=runtime_store)

        with self.assertRaisesRegex(runtime_requests.AppHostingError, "hidden"):
            runtime_requests._runtime_session_for_request(
                state,
                request={"runtime_session_id": "hidden-child"},
                workspace_id="default",
                app_id="video-studio",
                parsed=SimpleNamespace(),
                start_path=repo_root,
            )
        with self.assertRaisesRegex(runtime_requests.AppHostingError, "hidden"):
            runtime_requests._apply_one_runtime_interrupt_request(
                state,
                request={"turn_id": "hidden-turn"},
                workspace_id="default",
                app_id="video-studio",
            )

    def test_app_runtime_interrupt_retries_provider_after_cancellation_handoff(self) -> None:
        runtime_store = self._runtime_store()
        now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
        repo_root = make_temp_repo_root(self)
        session = create_runtime_session(
            runtime_store,
            session_id="app-owned-session",
            workspace_id="default",
            agent_id="video-agent",
            source_app_id="video-studio",
            start_path=repo_root,
        )
        runtime_store.save_turn(
            RuntimeTurnRecord(
                turn_id="app-owned-turn",
                session_id=session.session_id,
                workspace_id="default",
                status="active",
                input_text="render",
                created_at=now,
                updated_at=now,
                started_at=now,
                completed_at=None,
                failure_reason=None,
            )
        )
        state = SimpleNamespace(
            runtime_store=runtime_store,
            provider_store=object(),
            runtime_event_bus=None,
        )

        with (
            patch.object(runtime_requests, "_resolved_provider_id", return_value="codex"),
            patch.object(runtime_requests, "interrupt_runtime_provider_turn", side_effect=[False, True]) as interrupt,
            patch.object(runtime_requests, "set_thread_availability"),
            patch.object(runtime_requests, "release_idle_runtime_processes", return_value=0),
            patch.object(runtime_requests, "dispatch_source_app_runtime_event"),
        ):
            result = runtime_requests._apply_one_runtime_interrupt_request(
                state,
                request={"turn_id": "app-owned-turn"},
                workspace_id="default",
                app_id="video-studio",
            )

        self.assertEqual(interrupt.call_count, 2)
        self.assertNotIn("wait_for_termination", interrupt.call_args_list[0].kwargs)
        self.assertTrue(interrupt.call_args_list[1].kwargs["wait_for_termination"])
        self.assertTrue(result["provider_interrupted"])
        self.assertEqual(result["status"], "cancelled")
        self.assertIsNotNone(runtime_store.get_turn("app-owned-turn").cancellation_requested_at)

    def test_dependency_backend_request_result_is_only_exposed_to_callback(self) -> None:
        callback_payloads: list[dict[str, object]] = []
        callback_invocations: list[dict[str, object]] = []
        result = {
            "json": {"ok": True},
            "dependency_backend_requests": [
                {
                    "request_id": "resolve-local-path",
                    "dependency_alias": "storage-local-path",
                    "body": {"action": "file.local_path.resolve", "stable_storage_file_id": "file_drive"},
                    "callback": {"action": "store_resolved_local_path", "payload": {"job_id": "render-1"}},
                }
            ],
        }
        parsed = SimpleNamespace(
            contract=SimpleNamespace(
                permissions=SimpleNamespace(runtime=SimpleNamespace(create_sessions=False)),
                capabilities=SimpleNamespace(data_events=[]),
            )
        )

        def fake_invoke_dependency_backend(*_args, **_kwargs):
            return {
                "status_code": 200,
                "dependency_provider_app_id": "storage",
                "json": {"local_path": "/tmp/storage/file.bin"},
            }

        def fake_run_entrypoint(_entrypoint, *, payload, **kwargs):
            callback_payloads.append(payload)
            callback_invocations.append(kwargs)
            return {"status_code": 200, "json": {"stored": True}}

        callback_state = SimpleNamespace(
            app_event_bus=None,
            observability_store=None,
            app_store=SimpleNamespace(
                get_workspace_app_binding=lambda **_kwargs: SimpleNamespace(workspace_id="default", app_id="video-studio")
            ),
        )
        with (
            patch.object(runtime_requests, "_invoke_dependency_backend", fake_invoke_dependency_backend),
            patch(
                "core.api.sidecar_entrypoint_invocation.run_json_entrypoint_with_sidecars",
                fake_run_entrypoint,
            ),
        ):
            runtime_requests.apply_app_runtime_requests(
                callback_state,
                result=result,
                workspace_id="default",
                app_id="video-studio",
                source_root=Path("/apps/video-studio"),
                backend_entrypoint="backend/app_backend.py",
                data_root="workspaces/default/data/video-studio",
                parsed=parsed,
                start_path=Path(__file__).resolve().parents[3],
            )

        public_result = result["json"]["dependency_backend_request_results"][0]
        callback_body = callback_payloads[0]["body"]
        self.assertNotIn("json", public_result)
        self.assertEqual(public_result["callback_status_code"], 200)
        self.assertEqual(callback_body["action"], "store_resolved_local_path")
        self.assertEqual(callback_body["job_id"], "render-1")
        self.assertEqual(callback_body["dependency_backend_result"]["json"], {"local_path": "/tmp/storage/file.bin"})
        self.assertEqual(callback_invocations[0]["surface"], "backend")
        self.assertIsNone(callback_invocations[0]["runtime_session_id"])


if __name__ == "__main__":
    unittest.main()
