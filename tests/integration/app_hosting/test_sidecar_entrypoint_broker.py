"""Integration tests for the ephemeral app-entrypoint sidecar broker."""

from __future__ import annotations

import os
from dataclasses import replace
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from core.api.sidecar_entrypoint_broker import (
    AppSidecarEntrypointBroker,
    SidecarEntrypointServiceTarget,
)
from core.api.sidecar_entrypoint_invocation import run_json_entrypoint_with_sidecars
from core.api.sidecar_proxy import AuthorizedSidecarTarget, BufferedSidecarResponse
from core.app_sdk.app_sidecar import AppSidecarRequestError, AppSidecarUnavailableError, app_sidecar
from core.apps.contracts import (
    build_app_contract,
    build_app_entrypoints,
    build_app_services,
    build_http_sidecar_entrypoint_access,
    build_http_sidecar_entrypoint_surface,
    build_http_sidecar_proxy,
    build_http_sidecar_route_policy,
    build_http_sidecar_route_rule,
    build_http_sidecar_spec,
    build_parsed_app_contract,
)
from core.apps.models import WorkspaceAppBindingRecord
from core.observability.store import ObservabilityCollections, ObservabilityDocumentStore
from core.shared.in_memory_collection import InMemoryCollection
from core.shared.entrypoints import EntrypointShutdownController


class SidecarEntrypointBrokerIntegrationTests(unittest.TestCase):
    def test_reused_worker_receives_fresh_capabilities_and_cannot_reuse_previous_ones(self) -> None:
        target = self._target()
        parsed = replace(target.parsed, contract=replace(target.parsed.contract,
            entrypoints=build_app_entrypoints(mcp="worker.py", json_worker="worker.py")))
        controller = EntrypointShutdownController()
        self.addCleanup(controller.begin_shutdown)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("core", "apps", "workspaces", "scripts"):
                (root / name).mkdir()
            (root / "AGENTS.md").write_text("")
            app_root = root / "apps" / "sidecar-demo"
            app_root.mkdir()
            worker = app_root / "worker.py"
            worker.write_text('''
import os
from core.app_sdk.json_worker import serve_json_requests
from core.app_sdk.app_sidecar import app_sidecar, AppSidecarError
previous = None
def handle(payload):
    global previous
    previous_denied = False
    if previous is not None:
        try:
            app_sidecar(previous, 'opendesign').get('/api/projects/od_project_1')
        except AppSidecarError:
            previous_denied = True
    response = app_sidecar(payload, 'opendesign').get('/api/projects/od_project_1')
    previous = payload  # Intentionally hostile fixture probes revoked capabilities.
    return {'pid': os.getpid(), 'id': response.json()['id'], 'previous_denied': previous_denied,
            'invocation': payload['entrypoint_invocation_id']}
serve_json_requests(handle)
''')
            results = []
            with patch.dict(os.environ, {"PYTHONPATH": str(Path(__file__).resolve().parents[3])}), patch(
                "core.api.sidecar_entrypoint_broker.request_authorized_sidecar_buffered",
                return_value=BufferedSidecarResponse(status_code=200, headers={"content-type": "application/json"}, body=b'{"id":"one"}'),
            ):
                for actor in ("user-1", "user-1", "user-2"):
                    results.append(run_json_entrypoint_with_sidecars(worker,
                        payload={"surface": "mcp", "workspace_id": "workspace-a", "app_id": "sidecar-demo"},
                        cwd=app_root, binding=target.binding, parsed=parsed, surface="reference", start_path=root,
                        actor_user_id=actor, runtime_session_id=None, shutdown_controller=controller))
            controller.begin_shutdown()
        self.assertEqual(results[0]["pid"], results[1]["pid"])
        self.assertNotEqual(results[1]["pid"], results[2]["pid"])
        self.assertTrue(results[1]["previous_denied"])
        self.assertFalse(results[2]["previous_denied"])
        self.assertEqual({result["id"] for result in results}, {"one"})
        self.assertEqual(len({result["invocation"] for result in results}), 3)

    def test_entrypoint_wrapper_delivers_sdk_capability_only_for_process_lifetime(self) -> None:
        calls: list[dict] = []

        def sender(_target, **request):
            calls.append(request)
            return BufferedSidecarResponse(
                status_code=200,
                headers={"content-type": "application/json"},
                body=b'{"id":"od_project_1"}',
            )

        target = self._target()
        with tempfile.TemporaryDirectory() as temp:
            repo_root = Path(temp) / "maverick"
            app_root = repo_root / "apps" / "sidecar-demo"
            app_root.mkdir(parents=True)
            for name in ("core", "workspaces", "scripts"):
                (repo_root / name).mkdir()
            (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
            entrypoint = app_root / "probe.py"
            entrypoint.write_text(
                "from core.app_sdk.app_sidecar import app_sidecar\n"
                "from core.app_sdk.runtime import emit_json, read_entrypoint_payload\n"
                "payload = read_entrypoint_payload()\n"
                "service = payload.raw['app_sidecar']['services']['opendesign']\n"
                "response = app_sidecar(payload, 'opendesign').get('/api/projects/od_project_1')\n"
                "emit_json({'id': response.json()['id'], 'has_port': 'port' in service, "
                "'has_od_token': 'OD_API_TOKEN' in str(service)})\n",
                encoding="utf-8",
            )
            observability = self._observability_store()
            repository_root = Path(__file__).resolve().parents[3]
            with patch.dict(os.environ, {"PYTHONPATH": str(repository_root)}, clear=False), patch(
                "core.api.sidecar_entrypoint_broker.request_authorized_sidecar_buffered",
                side_effect=sender,
            ):
                result = run_json_entrypoint_with_sidecars(
                    entrypoint,
                    payload={
                        "surface": "cli",
                        "workspace_id": "workspace-a",
                        "app_id": "sidecar-demo",
                        "data_root": target.binding.data_root,
                    },
                    cwd=app_root,
                    binding=target.binding,
                    parsed=target.parsed,
                    surface="cli",
                    start_path=repo_root,
                    actor_user_id="user-1",
                    runtime_session_id="runtime-1",
                    observability_store=observability,
                )

        self.assertEqual(result, {"id": "od_project_1", "has_port": False, "has_od_token": False})
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["path"], "/api/projects/od_project_1")
        self.assertEqual(
            [record.action for record in observability.list_audit(source_domain="apps.sidecars.entrypoint")],
            [
                "sidecar.entrypoint_capability.issue",
                "sidecar.entrypoint_request.proxy",
                "sidecar.entrypoint_capability.revoke",
            ],
        )

    def test_reference_capability_is_invocation_scoped_audited_and_revoked(self) -> None:
        calls: list[dict] = []

        def sender(_target, **request):
            calls.append(request)
            return BufferedSidecarResponse(
                status_code=200,
                headers={"content-type": "application/json"},
                body=b'{"id":"od_project_1"}',
            )

        with tempfile.TemporaryDirectory() as temp:
            observability = self._observability_store()
            broker = AppSidecarEntrypointBroker(
                services=[SidecarEntrypointServiceTarget(target=self._target())],
                surface="reference",
                actor_user_id="user-1",
                runtime_session_id="runtime-1",
                start_path=Path(temp),
                observability_store=observability,
                request_sender=sender,
            )
            descriptor = broker.start()
            self.assertIsNotNone(descriptor)
            client = app_sidecar({"app_sidecar": descriptor}, "opendesign")

            response = client.get("/api/projects/od_project_1")
            with self.assertRaisesRegex(AppSidecarRequestError, "route_not_allowed"):
                client.post("/api/projects", json_body={"name": "forbidden"})
            socket_path = descriptor["services"]["opendesign"]["broker_socket"]
            capability = descriptor["services"]["opendesign"]["capability"]
            broker.close()
            with self.assertRaisesRegex(AppSidecarUnavailableError, "broker_unavailable"):
                client.get("/api/projects/od_project_1")

        self.assertEqual(response.json(), {"id": "od_project_1"})
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["method"], "GET")
        self.assertFalse(Path(socket_path).exists())
        audit = observability.list_audit(source_domain="apps.sidecars.entrypoint")
        self.assertEqual(
            [record.action for record in audit],
            [
                "sidecar.entrypoint_capability.issue",
                "sidecar.entrypoint_request.proxy",
                "sidecar.entrypoint_request.deny",
                "sidecar.entrypoint_capability.revoke",
            ],
        )
        self.assertEqual({record.payload["invocation_id"] for record in audit}, {broker.invocation_id})
        self.assertNotIn(capability, repr(audit))

    @staticmethod
    def _target() -> AuthorizedSidecarTarget:
        get_project = build_http_sidecar_route_rule(method="GET", path_template="/api/projects/{id}")
        create_project = build_http_sidecar_route_rule(method="POST", path_template="/api/projects")
        sidecar = build_http_sidecar_spec(
            service_id="opendesign",
            command=["python3", "server.py"],
            entrypoint_access=build_http_sidecar_entrypoint_access(
                ttl_seconds=30,
                request_budget=2,
                max_request_body_bytes=4096,
                max_response_body_bytes=65536,
                surfaces=[
                    build_http_sidecar_entrypoint_surface(surface="reference", routes=[get_project]),
                    build_http_sidecar_entrypoint_surface(surface="cli", routes=[get_project, create_project]),
                ],
            ),
            proxy=build_http_sidecar_proxy(
                mount="/sidecar",
                route_policy=build_http_sidecar_route_policy(
                    pass_through=[get_project, create_project],
                ),
            ),
        )
        parsed = build_parsed_app_contract(
            app_id="sidecar-demo",
            name="Sidecar Demo",
            version="0.1.0",
            description="Test app.",
            publisher="maverick",
            contract=build_app_contract(services=build_app_services(http_sidecars=[sidecar])),
        )
        binding = WorkspaceAppBindingRecord(
            binding_id="binding-1",
            workspace_id="workspace-a",
            app_id="sidecar-demo",
            source_record_id="source-1",
            source_kind="platform",
            status="enabled",
            active_version="0.1.0",
            data_root="/workspace/data/sidecar-demo",
            installed_at="2026-08-03T00:00:00+00:00",
            updated_at="2026-08-03T00:00:00+00:00",
            public_app_id="sidecar-demo",
            local_app_id="sidecar-demo",
            mount_app_id="sidecar-demo",
        )
        return AuthorizedSidecarTarget(
            binding=binding,
            source_root=Path("/app"),
            parsed=parsed,
            sidecar=sidecar,
        )

    @staticmethod
    def _observability_store() -> ObservabilityDocumentStore:
        return ObservabilityDocumentStore(
            ObservabilityCollections(
                events=InMemoryCollection(),
                audit=InMemoryCollection(),
                metrics=InMemoryCollection(),
            )
        )


if __name__ == "__main__":
    unittest.main()
