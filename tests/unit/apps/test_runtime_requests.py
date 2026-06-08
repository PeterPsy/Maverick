from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import core.apps.runtime_requests as runtime_requests


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

    def test_dependency_backend_request_result_is_only_exposed_to_callback(self) -> None:
        callback_payloads: list[dict[str, object]] = []
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

        def fake_run_entrypoint(_entrypoint, *, payload, **_kwargs):
            callback_payloads.append(payload)
            return {"status_code": 200, "json": {"stored": True}}

        with (
            patch.object(runtime_requests, "_invoke_dependency_backend", fake_invoke_dependency_backend),
            patch.object(runtime_requests, "run_json_entrypoint", fake_run_entrypoint),
        ):
            runtime_requests.apply_app_runtime_requests(
                SimpleNamespace(app_event_bus=None),
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


if __name__ == "__main__":
    unittest.main()
