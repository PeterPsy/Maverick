"""Hosted/core end-to-end coverage for the Senses Phase 7 pipeline."""

from __future__ import annotations

from base64 import b64encode
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import BytesIO
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch

from core.api.platform_host import PlatformHost
from core.api.platform_state import PlatformState, bootstrap_platform_state
from core.apps.dependencies import save_app_dependency_selection
import core.apps.runtime_requests as runtime_requests
from core.apps.service import install_store_app, register_app_source_from_contract
from core.runtime.turn_submission_service_output import _queue_turn_with_event
from tests.support.env import apply_test_environment_defaults
from tests.support.repo import link_app_sources, make_temp_repo_root


MAVERICK_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / "core").is_dir())
SENSES_BACKEND_ROOT = MAVERICK_ROOT / "apps" / "senses" / "backend"
sys.path.insert(0, str(SENSES_BACKEND_ROOT))
import service as senses_service


@dataclass(frozen=True)
class HostedSensesStack:
    repo_root: Path
    state: PlatformState
    app: PlatformHost
    cookie: str
    senses_data_root: Path


class SensesHostedE2ETest(unittest.TestCase):
    def setUp(self) -> None:
        apply_test_environment_defaults()

    def test_hosted_manifest_matches_ios_preflight_contract(self) -> None:
        stack = self._hosted_stack()

        status, manifest = self._post_senses(stack, {"action": "manifest"})

        self.assertEqual(status, 200)
        self.assertEqual(manifest["action"], "manifest")
        self.assertIs(manifest["available"], True)
        self.assertIs(manifest["ok"], True)
        self.assertEqual(manifest["dependency_resolution"]["status"], "resolved")

    def test_hosted_ingest_storage_dispatch_and_chat_deep_link_pipeline(self) -> None:
        stack = self._hosted_stack()
        completed = self._pair_device(stack)

        status, accepted = self._post_senses(
            stack,
            self._capture_request(
                completed,
                request_id="hosted-normal-1",
                idempotency_key="hosted-normal-1",
            ),
        )

        self.assertEqual(status, 202)
        self.assertEqual(accepted["storage"]["status"], "pending")
        self.assertNotIn("dependency_backend_requests", accepted)
        self.assertEqual(
            accepted["dependency_backend_request_results"],
            [
                {
                    "request_id": f"write-{accepted['capture_id']}",
                    "dependency_alias": "storage-file-content-write",
                    "provider_app_id": "storage",
                    "status": "completed",
                    "status_code": 200,
                    "callback_status_code": 200,
                }
            ],
        )

        capture_id = str(accepted["capture_id"])
        status, fetched = self._post_senses(stack, {"action": "captures.get", "capture_id": capture_id})
        self.assertEqual(status, 200)
        capture = fetched["capture"]
        self.assertEqual(capture["status"], "stored")
        self.assertEqual(capture["storage"]["status"], "stored")
        storage_path = self._workspace_path(stack, str(capture["storage"]["workspace_relative_path"]))
        self.assertTrue(storage_path.is_file())

        runtime_results: list[dict[str, object]] = []
        with (
            patch.object(runtime_requests, "submit_runtime_turn_async", self._fake_submit_runtime_turn(runtime_results)),
            patch(
                "core.runtime.turn_submission_service_output.schedule_runtime_thread_title_generation",
                lambda *_args, **_kwargs: None,
            ),
        ):
            status, dispatch = self._post_senses(
                stack,
                {"action": "routing.dispatch_capture", "capture_id": capture_id},
            )

        self.assertEqual(status, 202)
        self.assertEqual(dispatch["status"], "dispatch_pending")
        self.assertNotIn("runtime_launch_requests", dispatch)
        self.assertEqual(len(dispatch["runtime_request_results"]), 1)
        self.assertEqual(dispatch["runtime_request_results"][0]["status"], "submitted")
        self.assertEqual(dispatch["runtime_request_results"][0]["callback_status_code"], 200)
        self.assertEqual(len(runtime_results), 1)

        runtime_request = self._stored_runtime_request(stack, capture_id)
        attachment = runtime_request["attachments"][0]
        self.assertEqual(attachment["workspace_relative_path"], capture["storage"]["workspace_relative_path"])
        self.assertEqual(attachment["content_type"], "image/jpeg")
        self.assertEqual(self._workspace_path(stack, attachment["workspace_relative_path"]), storage_path)
        self.assertEqual(runtime_request["agent_id"], "chat")
        self.assertEqual(runtime_request["agent_type_id"], "chat")
        self.assertEqual(runtime_request["requested_mode"], "sandbox")
        self.assertEqual(runtime_request["title"], "Hosted iPhone - domanda visiva")
        self.assertEqual(runtime_request["app_references"][0]["app_id"], "senses")
        self.assertEqual(runtime_request["app_references"][0]["entity_type"], "capture")
        self.assertEqual(runtime_request["app_references"][0]["entity_id"], capture_id)
        self.assertEqual(runtime_request["callback"]["action"], "runtime_dispatch.completed")
        self.assertEqual(runtime_request["callback"]["payload"]["capture_id"], capture_id)
        queued_attachment = runtime_results[0]["attachments"][0]
        self.assertEqual(queued_attachment["workspace_relative_path"], attachment["workspace_relative_path"])
        self.assertEqual(queued_attachment["relative_path"], attachment["workspace_relative_path"])
        self.assertEqual(queued_attachment["content_type"], attachment["content_type"])
        self.assertEqual(queued_attachment["id"], attachment["id"])
        self.assertEqual(runtime_results[0]["app_references"], runtime_request["app_references"])

        runtime_session_id = str(dispatch["runtime_request_results"][0]["runtime_session_id"])
        turn_id = str(dispatch["runtime_request_results"][0]["turn_id"])
        session = stack.state.runtime_store.get_session(runtime_session_id)
        thread = stack.state.runtime_store.get_thread(runtime_session_id)
        self.assertEqual(session.agent_id, "chat")
        self.assertEqual(session.source_app_id, "senses")
        self.assertEqual(thread.source_app_id, "senses")
        self.assertEqual(thread.agent_type_id, "chat")

        status, after_callback = self._post_senses(stack, {"action": "captures.get", "capture_id": capture_id})
        self.assertEqual(status, 200)
        stored_capture = after_callback["capture"]
        self.assertEqual(stored_capture["runtime_session_id"], runtime_session_id)
        self.assertEqual(stored_capture["thread_id"], runtime_session_id)
        self.assertEqual(stored_capture["turn_id"], turn_id)
        self.assertEqual(stored_capture["chat"]["app_id"], "chat")
        self.assertEqual(stored_capture["chat"]["status"], "linked")
        self.assertEqual(stored_capture["chat"]["deep_link"], f"/app/chat/threads/{runtime_session_id}")
        self._assert_chat_deep_link_mounts(stack, stored_capture["chat"]["deep_link"], runtime_session_id)
        self.assertEqual(after_callback["runtime_dispatch_attempts"][0]["status"], "submitted")
        self.assertEqual(after_callback["runtime_dispatch_attempts"][0]["turn_id"], turn_id)

    def test_hosted_storage_recovery_reissues_upsert_and_recovers_lost_callback(self) -> None:
        stack = self._hosted_stack()
        completed = self._pair_device(stack)
        request = self._capture_request(
            completed,
            request_id="hosted-recovery-1",
            idempotency_key="hosted-recovery-key",
        )

        with patch.object(
            runtime_requests,
            "_safe_dependency_backend_request_callback",
            lambda *_args, **_kwargs: {"status_code": 0},
        ):
            status, first = self._post_senses(stack, dict(request))

        self.assertEqual(status, 202)
        self.assertEqual(first["dependency_backend_request_results"][0]["status"], "completed")
        self.assertEqual(first["dependency_backend_request_results"][0]["callback_status_code"], 0)
        capture_id = str(first["capture_id"])
        original_path = str(first["storage"]["workspace_relative_path"])
        self.assertTrue(self._workspace_path(stack, original_path).is_file())

        status, pending = self._post_senses(stack, {"action": "captures.get", "capture_id": capture_id})
        self.assertEqual(status, 200)
        self.assertEqual(pending["capture"]["status"], "storage_pending")
        self.assertEqual(pending["capture"]["storage"]["status"], "pending")

        stale_at = (
            datetime.now(tz=UTC) - timedelta(seconds=senses_service.STORAGE_PENDING_LEASE_SECONDS + 5)
        ).isoformat()
        with closing(sqlite3.connect(stack.senses_data_root / "senses.sqlite")) as db:
            db.execute(
                "UPDATE captures SET updated_at = ? WHERE workspace_id = ? AND capture_id = ?",
                (stale_at, "default", capture_id),
            )
            db.commit()

        storage_bodies: list[dict[str, object]] = []
        original_invoke_dependency_backend = runtime_requests._invoke_dependency_backend

        def capture_storage_body(*args, **kwargs):
            body = kwargs.get("body")
            if isinstance(body, dict):
                storage_bodies.append(dict(body))
            return original_invoke_dependency_backend(*args, **kwargs)

        with patch.object(runtime_requests, "_invoke_dependency_backend", capture_storage_body):
            status, replay = self._post_senses(stack, dict(request))

        self.assertEqual(status, 200)
        self.assertEqual(replay["capture_id"], capture_id)
        self.assertEqual(replay["dependency_backend_request_results"][0]["status"], "completed")
        self.assertEqual(replay["dependency_backend_request_results"][0]["callback_status_code"], 200)
        self.assertEqual(len(storage_bodies), 1)
        self.assertEqual(storage_bodies[0]["action"], "file.content.write")
        self.assertEqual(storage_bodies[0]["mode"], "upsert")
        self.assertIs(storage_bodies[0]["confirm"], True)
        self.assertEqual(storage_bodies[0]["workspace_relative_path"], original_path)

        status, recovered = self._post_senses(stack, {"action": "captures.get", "capture_id": capture_id})
        self.assertEqual(status, 200)
        self.assertEqual(recovered["capture"]["status"], "stored")
        self.assertEqual(recovered["capture"]["storage"]["status"], "stored")
        self.assertEqual(recovered["capture"]["storage"]["workspace_relative_path"], original_path)
        with closing(sqlite3.connect(stack.senses_data_root / "senses.sqlite")) as db:
            statuses = [
                row[0]
                for row in db.execute(
                    "SELECT status FROM captures WHERE workspace_id = ? AND capture_id = ?",
                    ("default", capture_id),
                ).fetchall()
            ]
        self.assertEqual(statuses, ["stored"])
        self.assertNotIn("storage_failed", statuses)

    # Browser is not used as a UI smoke harness here: app_id=browser is a sealed,
    # full-access-only P0 app with no frontend, and the repo's Browser tests cover
    # broker/policy behavior through stubs rather than deterministic local UI e2e.
    # These hosted backend tests temporarily cover the Senses pipeline until Browser
    # exposes a local development-inspector harness suitable for app UI assertions.

    def _hosted_stack(self) -> HostedSensesStack:
        repo_root = make_temp_repo_root(self, include_core=True)
        link_app_sources(repo_root, ["base-shell", "chat", "storage", "senses"])
        state = bootstrap_platform_state(
            start_path=repo_root,
            install_builtin_apps=False,
            register_builtin_provider_definitions=False,
        )
        for app_id in ("base-shell", "chat", "storage", "senses"):
            source = register_app_source_from_contract(
                state.app_store,
                source_kind="platform",
                source_path=str(repo_root / "apps" / app_id),
            )
            install_store_app(
                state.app_store,
                source_id=source.source_id,
                workspace_id="default",
                start_path=repo_root,
                observability_store=state.observability_store,
            )
        for alias in ("storage-file-content-write", "storage-file-catalog"):
            save_app_dependency_selection(
                state.app_store,
                workspace_id="default",
                consumer_app_id="senses",
                alias=alias,
                provider_app_ids=["storage"],
                workspace_store=state.workspace_store,
                start_path=repo_root,
            )
        save_app_dependency_selection(
            state.app_store,
            workspace_id="default",
            consumer_app_id="senses",
            alias="chat-communication",
            provider_app_ids=["chat"],
            workspace_store=state.workspace_store,
            start_path=repo_root,
        )
        app = PlatformHost(state, start_path=repo_root)
        cookie = self._login(app)
        binding = state.app_store.get_workspace_app_binding(workspace_id="default", app_id="senses")
        return HostedSensesStack(
            repo_root=repo_root,
            state=state,
            app=app,
            cookie=cookie,
            senses_data_root=Path(binding.data_root),
        )

    def _assert_chat_deep_link_mounts(
        self,
        stack: HostedSensesStack,
        deep_link: object,
        runtime_session_id: str,
    ) -> None:
        self.assertIsInstance(deep_link, str)
        shell_status, shell_payload, _headers = self._invoke(stack.app, path=deep_link, cookie=stack.cookie)
        self.assertEqual(shell_status, 200, shell_payload)

        chat_status, chat_payload, _headers = self._invoke(
            stack.app,
            path=f"/apps/chat/threads/{runtime_session_id}",
            cookie=stack.cookie,
        )
        self.assertEqual(chat_status, 200, chat_payload)

    def _pair_device(self, stack: HostedSensesStack) -> dict[str, object]:
        status, started = self._post_senses(stack, {"action": "pairing.start"})
        self.assertEqual(status, 201)
        status, completed = self._post_senses(
            stack,
            {
                "action": "pairing.complete",
                "code": started["pairing"]["code"],
                "device_display_name": "Hosted iPhone",
                "device_kind": "ios",
                "platform": "ios",
                "client_device_id": "hosted-ios-client",
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(completed["device_session"]["auth_mode"], "user_session_mvp")
        return completed

    def _login(self, app: PlatformHost) -> str:
        status, _payload, headers = self._invoke(
            app,
            path="/api/auth/login",
            method="POST",
            body={"username": "admin", "password": "maverick"},
        )
        self.assertEqual(status, 200)
        return headers["Set-Cookie"].split(";", 1)[0]

    def _post_senses(self, stack: HostedSensesStack, body: dict[str, object]) -> tuple[int, dict[str, object]]:
        status, payload, _headers = self._invoke(
            stack.app,
            path="/api/apps/senses/backend",
            method="POST",
            body=body,
            cookie=stack.cookie,
        )
        self.assertIsInstance(payload, dict)
        return status, payload

    def _invoke(
        self,
        app: PlatformHost,
        *,
        path: str,
        method: str = "GET",
        body: dict[str, object] | None = None,
        cookie: str | None = None,
    ) -> tuple[int, dict[str, object] | bytes, dict[str, str]]:
        payload = b"" if body is None else json.dumps(body).encode("utf-8")
        headers: dict[str, str] = {}
        environ = {
            "PATH_INFO": path,
            "REQUEST_METHOD": method,
            "CONTENT_LENGTH": str(len(payload)),
            "CONTENT_TYPE": "application/json",
            "QUERY_STRING": "",
            "wsgi.input": BytesIO(payload),
        }
        if cookie is not None:
            environ["HTTP_COOKIE"] = cookie

        def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
            headers.update(dict(response_headers))
            headers["__status__"] = status

        raw = b"".join(app(environ, start_response))
        status_code = int(headers["__status__"].split()[0])
        if "application/json" in headers.get("Content-Type", ""):
            return status_code, json.loads(raw.decode("utf-8")), headers
        return status_code, raw, headers

    def _capture_request(
        self,
        completed: dict[str, object],
        *,
        request_id: str,
        idempotency_key: str,
    ) -> dict[str, object]:
        body = self._jpeg_with_exif()
        return {
            "action": "ingest.frame",
            "schema_version": "senses.capture.v1",
            "request_id": request_id,
            "device_id": completed["device"]["device_id"],
            "device_session_id": completed["device_session"]["device_session_id"],
            "idempotency_key": idempotency_key,
            "client_capture_id": f"local-{request_id}",
            "input_mode": "vision.snapshot",
            "prompt": "Cosa sto guardando?",
            "content_type": "image/jpeg",
            "content_base64": b64encode(body).decode("ascii"),
            "content_sha256": hashlib.sha256(body).hexdigest(),
            "captured_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
            "metadata": {"adapter_id": "hosted-ios", "width": 1600, "height": 1200},
        }

    def _fake_submit_runtime_turn(self, captured: list[dict[str, object]]):
        def fake_submit_runtime_turn_async(
            submit_state,
            *,
            session,
            input_text,
            client_message_id=None,
            attachments=None,
            app_references=None,
            on_queued=None,
        ):
            captured.append(
                {
                    "runtime_session_id": session.session_id,
                    "input_text": input_text,
                    "client_message_id": client_message_id,
                    "attachments": attachments or [],
                    "app_references": app_references or [],
                }
            )
            turn, events = _queue_turn_with_event(
                submit_state,
                session=session,
                input_text=input_text,
                provider_id="test-provider",
                client_message_id=client_message_id,
                attachments=attachments,
                app_references=app_references,
            )
            captured[-1]["turn_id"] = turn.turn_id
            if on_queued is not None:
                on_queued(turn, events)
            return turn, events

        return fake_submit_runtime_turn_async

    def _stored_runtime_request(self, stack: HostedSensesStack, capture_id: str) -> dict[str, object]:
        with closing(sqlite3.connect(stack.senses_data_root / "senses.sqlite")) as db:
            row = db.execute(
                """
                SELECT runtime_request_json
                FROM runtime_dispatch_attempts
                WHERE workspace_id = ? AND capture_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                ("default", capture_id),
            ).fetchone()
        self.assertIsNotNone(row)
        payload = json.loads(str(row[0]))
        self.assertIsInstance(payload, dict)
        return payload

    def _workspace_path(self, stack: HostedSensesStack, workspace_relative_path: str) -> Path:
        return stack.repo_root / "workspaces" / "default" / workspace_relative_path

    def _jpeg_with_exif(self) -> bytes:
        exif_payload = b"Exif\x00\x00GPSSECRET"
        app1 = b"\xff\xe1" + (len(exif_payload) + 2).to_bytes(2, "big") + exif_payload
        jfif_payload = b"JFIF\x00"
        app0 = b"\xff\xe0" + (len(jfif_payload) + 2).to_bytes(2, "big") + jfif_payload
        dqt_payload = b"\x00" + bytes([1] * 64)
        dqt = b"\xff\xdb" + (len(dqt_payload) + 2).to_bytes(2, "big") + dqt_payload
        sof0_payload = b"\x08\x00\x01\x00\x01\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00"
        sof0 = b"\xff\xc0" + (len(sof0_payload) + 2).to_bytes(2, "big") + sof0_payload
        sos_payload = b"\x03\x01\x00\x02\x00\x03\x00\x00\x3f\x00"
        sos = b"\xff\xda" + (len(sos_payload) + 2).to_bytes(2, "big") + sos_payload
        return b"\xff\xd8" + app1 + app0 + dqt + sof0 + sos + b"\x11\x22\xff\xd9"


if __name__ == "__main__":
    unittest.main()
