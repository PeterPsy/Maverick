from __future__ import annotations

from base64 import b64encode
import json
import os
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / "apps" / "design-studio" / "backend"
sys.path.insert(0, str(BACKEND))

from delegation_errors import DelegationError  # noqa: E402
from delegation_service import DelegationService  # noqa: E402
from delegation_store import DelegationStore  # noqa: E402
from opendesign_client import (  # noqa: E402
    OpenDesignClient,
    OpenDesignNotFound,
    OpenDesignUnavailable,
)
from project_surfaces import ProjectSurfaces  # noqa: E402
from surface_service import SurfaceService  # noqa: E402


class FakeOpenDesign:
    def __init__(self) -> None:
        self.projects: dict[str, dict] = {}
        self.conversations: dict[str, list[dict]] = {}
        self.messages: dict[tuple[str, str], list[dict]] = {}
        self.runs: dict[str, dict] = {}
        self.uploads: list[dict] = []
        self.put_calls: list[dict] = []
        self.run_calls: list[dict] = []
        self.lose_next_run_response = False
        self.hide_next_recovery = False
        self.conceal_lost_run = False

    def list_projects(self) -> list[dict]:
        return list(self.projects.values())

    def get_project(self, project_id: str) -> dict:
        if project_id not in self.projects:
            raise OpenDesignNotFound("missing")
        return self.projects[project_id]

    def create_project(self, body: dict) -> dict:
        project_id = body["id"]
        project = {
            "id": project_id,
            "name": body["name"],
            "metadata": {"private": "must-not-leak"},
            "createdAt": 1,
            "updatedAt": 1,
        }
        conversation_id = f"conv_{project_id[-12:]}"
        self.projects[project_id] = project
        self.conversations[project_id] = [{
            "id": conversation_id,
            "projectId": project_id,
            "title": None,
            "createdAt": 1,
        }]
        self.messages[(project_id, conversation_id)] = []
        return {"project": project, "conversationId": conversation_id}

    def list_conversations(self, project_id: str) -> list[dict]:
        if project_id not in self.projects:
            raise OpenDesignNotFound("missing")
        return list(self.conversations.get(project_id, []))

    def create_conversation(self, project_id: str, body: dict) -> dict:
        conversation = {
            "id": f"conv_created_{len(self.conversations.get(project_id, [])) + 1}",
            "projectId": project_id,
            "title": body.get("title"),
            "createdAt": len(self.conversations.get(project_id, [])) + 2,
        }
        self.conversations.setdefault(project_id, []).append(conversation)
        self.messages[(project_id, conversation["id"])] = []
        return conversation

    def list_messages(self, project_id: str, conversation_id: str) -> list[dict]:
        if self.hide_next_recovery:
            self.hide_next_recovery = False
            raise OpenDesignUnavailable("lost recovery")
        messages = list(self.messages.get((project_id, conversation_id), []))
        if self.conceal_lost_run:
            return [message for message in messages if not message.get("runId")]
        return messages

    def put_message(
        self,
        project_id: str,
        conversation_id: str,
        message_id: str,
        body: dict,
    ) -> dict:
        saved = {**body, "id": message_id}
        messages = self.messages[(project_id, conversation_id)]
        messages[:] = [message for message in messages if message.get("id") != message_id]
        messages.append(saved)
        self.put_calls.append({
            "project_id": project_id,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "body": body,
        })
        return saved

    def upload_file(self, project_id: str, body: dict) -> dict:
        self.uploads.append({"project_id": project_id, "body": body})
        return {"name": body["name"], "path": body["name"], "hostPath": "/private"}

    def start_run(self, body: dict) -> dict:
        run_id = f"run_{len(self.run_calls) + 1}"
        self.run_calls.append(body)
        run = {
            "id": run_id,
            "status": "queued",
            "projectId": body["projectId"],
            "conversationId": body["conversationId"],
            "assistantMessageId": body["assistantMessageId"],
            "pid": 999,
            "eventsLogPath": "/private/events.log",
        }
        self.runs[run_id] = run
        self.messages[(body["projectId"], body["conversationId"])].append({
            "id": body["assistantMessageId"],
            "role": "assistant",
            "content": "secret transcript",
            "runId": run_id,
            "runStatus": "queued",
            "lastRunEventId": 1,
        })
        if self.lose_next_run_response:
            self.lose_next_run_response = False
            self.hide_next_recovery = True
            raise OpenDesignUnavailable("response lost")
        return {
            "runId": run_id,
            "conversationId": body["conversationId"],
            "assistantMessageId": body["assistantMessageId"],
        }

    def get_run(self, run_id: str) -> dict:
        if run_id not in self.runs:
            raise OpenDesignNotFound("missing")
        return self.runs[run_id]

    def cancel_run(self, run_id: str) -> dict:
        self.runs[run_id]["status"] = "canceled"
        self._set_message_status(run_id, "canceled", 9)
        return {"ok": True, "run": self.runs[run_id]}

    def get_result_package(self, run_id: str) -> dict:
        run = self.runs[run_id]
        return {
            "schema": "native",
            "run": {**run, "transcript": "do not persist"},
            "workspace": {"storage": {"baseDir": "/private/project"}},
            "events": {"logPath": "/private/events.log"},
            "project": {
                "id": run["projectId"],
                "name": self.projects[run["projectId"]]["name"],
                "fileCount": 3,
            },
            "artifacts": [{
                "file": "private/path/index.html",
                "kind": "html",
                "renderer": "browser",
                "title": "Landing page",
                "status": "ready",
                "manifest": {"body": "secret artifact body"},
            }],
        }

    def finish(self, run_id: str) -> None:
        self.runs[run_id]["status"] = "succeeded"
        self._set_message_status(run_id, "succeeded", 42)

    def _set_message_status(self, run_id: str, status: str, cursor: int) -> None:
        run = self.runs[run_id]
        for message in self.messages[(run["projectId"], run["conversationId"])]:
            if message.get("runId") == run_id:
                message["runStatus"] = status
                message["lastRunEventId"] = cursor


def payload(data_root: Path, workspace_id: str = "default") -> SimpleNamespace:
    return SimpleNamespace(
        raw={},
        app_id="design-studio",
        workspace_id=workspace_id,
        data_root=str(data_root),
    )


class NativeDelegationTests(unittest.TestCase):
    def test_delegation_writes_one_visible_brief_and_persists_no_semantic_body(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            client = FakeOpenDesign()
            service = DelegationService(payload(root), client=client, clock_ms=lambda: 1234)
            arguments = {
                "brief": "Create a calm portfolio landing page.",
                "idempotency_key": "portfolio-v1",
                "model": "openrouter/deepseek-v4-flash",
                "attachments": [{
                    "name": "logo.svg",
                    "media_type": "image/svg+xml",
                    "content_base64": b64encode(b"<svg>authorized</svg>").decode("ascii"),
                    "authorized": True,
                }],
            }
            result = service.delegate(arguments)
            replay = service.delegate(arguments)

            self.assertEqual(len(client.put_calls), 1)
            self.assertEqual(len(client.run_calls), 1)
            self.assertTrue(replay["idempotent_replay"])
            visible = "Brief delegated by Maverick\n\nCreate a calm portfolio landing page."
            self.assertEqual(client.put_calls[0]["body"]["content"], visible)
            self.assertEqual(client.run_calls[0]["message"], visible)
            self.assertEqual(client.run_calls[0]["currentPrompt"], visible)
            self.assertEqual(client.run_calls[0]["model"], "openrouter/deepseek-v4-flash")
            self.assertNotIn("history", client.run_calls[0])
            self.assertNotIn("system", client.run_calls[0])
            self.assertNotIn("runtime_session_id", client.run_calls[0])
            self.assertEqual(result["delegation"]["status"], "queued")
            self.assertRegex(
                result["delegation"]["deep_link"],
                r"^/app/design-studio/projects/[^/]+/conversations/[^/]+$",
            )

            persisted = (root / "delegations" / "state.json").read_text(encoding="utf-8")
            for forbidden in (
                "Create a calm portfolio",
                "authorized",
                "content_base64",
                "openrouter/deepseek",
                "runtime_session",
            ):
                self.assertNotIn(forbidden, persisted)

    def test_unauthorized_attachment_is_rejected_before_native_or_store_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            client = FakeOpenDesign()
            service = DelegationService(payload(root), client=client)
            with self.assertRaises(DelegationError) as raised:
                service.delegate({
                    "brief": "Use this file.",
                    "idempotency_key": "unauthorized",
                    "attachments": [{
                        "name": "private.txt",
                        "content_base64": b64encode(b"private").decode("ascii"),
                    }],
                })
            self.assertEqual(raised.exception.code, "delegation_input_invalid")
            self.assertFalse(client.projects)
            self.assertFalse((root / "delegations/state.json").exists())

    def test_response_loss_is_recovered_without_duplicate_message_or_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            client = FakeOpenDesign()
            client.lose_next_run_response = True
            service = DelegationService(payload(root), client=client)
            arguments = {"brief": "Build the hero.", "idempotency_key": "loss-safe"}

            with self.assertRaises(DelegationError) as raised:
                service.delegate(arguments)
            self.assertEqual(raised.exception.code, "delegation_unavailable")
            retried = service.delegate(arguments)

            self.assertTrue(retried["idempotent_replay"])
            self.assertEqual(retried["delegation"]["opendesign"]["run_id"], "run_1")
            self.assertEqual(len(client.put_calls), 1)
            self.assertEqual(len(client.run_calls), 1)

    def test_uncertain_submission_is_fenced_before_retry_can_start_another_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            client = FakeOpenDesign()
            client.lose_next_run_response = True
            client.conceal_lost_run = True
            service = DelegationService(payload(Path(temporary)), client=client)
            arguments = {"brief": "Build the hero.", "idempotency_key": "fenced-loss"}

            with self.assertRaises(DelegationError):
                service.delegate(arguments)
            with self.assertRaises(DelegationError) as retried:
                service.delegate(arguments)

            self.assertEqual(retried.exception.code, "delegation_submission_uncertain")
            self.assertEqual(len(client.put_calls), 1)
            self.assertEqual(len(client.run_calls), 1)

    def test_idempotency_key_is_bound_to_brief_model_and_attachments(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            client = FakeOpenDesign()
            service = DelegationService(payload(root), client=client)
            original = {
                "brief": "First brief.",
                "idempotency_key": "bound-input",
                "model": "model/one",
                "attachments": [{
                    "name": "source.txt",
                    "content_base64": b64encode(b"one").decode("ascii"),
                    "authorized": True,
                }],
            }
            service.delegate(original)

            for changed in (
                {**original, "brief": "Second brief."},
                {**original, "model": "model/two"},
                {
                    **original,
                    "attachments": [{
                        **original["attachments"][0],
                        "content_base64": b64encode(b"two").decode("ascii"),
                    }],
                },
            ):
                with self.assertRaises(DelegationError) as raised:
                    service.delegate(changed)
                self.assertEqual(raised.exception.code, "idempotency_key_reused")
            self.assertEqual(len(client.run_calls), 1)

    def test_heartbeat_keeps_a_slow_start_run_lease_exclusive(self) -> None:
        class BlockingOpenDesign(FakeOpenDesign):
            def __init__(self) -> None:
                super().__init__()
                self.entered = threading.Event()
                self.resume = threading.Event()

            def start_run(self, body: dict) -> dict:
                self.entered.set()
                self.resume.wait(timeout=2)
                return super().start_run(body)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            client = BlockingOpenDesign()
            arguments = {"brief": "Slow run.", "idempotency_key": "heartbeat"}
            service = DelegationService(
                payload(root),
                client=client,
                heartbeat_interval_seconds=0.01,
            )
            outcome: list[object] = []

            def submit() -> None:
                try:
                    outcome.append(service.delegate(arguments))
                except Exception as error:  # pragma: no cover - asserted below
                    outcome.append(error)

            with patch("delegation_store.LEASE_SECONDS", 0.04):
                thread = threading.Thread(target=submit)
                thread.start()
                self.assertTrue(client.entered.wait(timeout=1))
                time.sleep(0.08)
                concurrent = DelegationService(payload(root), client=client).delegate(arguments)
                client.resume.set()
                thread.join(timeout=2)

            self.assertTrue(concurrent["in_progress"])
            self.assertFalse(thread.is_alive())
            self.assertEqual(len(outcome), 1)
            self.assertIsInstance(outcome[0], dict)
            self.assertEqual(len(client.run_calls), 1)

    def test_terminal_status_persists_only_display_safe_result_references(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            client = FakeOpenDesign()
            service = DelegationService(payload(root), client=client)
            delegated = service.delegate({"brief": "Create it.", "idempotency_key": "terminal"})
            delegation_id = delegated["delegation"]["delegation_id"]
            client.finish("run_1")

            result = service.result(delegation_id)

            self.assertTrue(result["result_available"])
            self.assertEqual(result["delegation"]["status"], "succeeded")
            self.assertEqual(result["delegation"]["event_cursor"], "42")
            artifact = result["delegation"]["result_references"]["artifacts"][0]
            self.assertEqual(artifact["title"], "Landing page")
            self.assertNotIn("file", artifact)
            persisted = (root / "delegations" / "state.json").read_text(encoding="utf-8")
            for forbidden in ("/private", "transcript", "manifest", "artifact body", '"pid"'):
                self.assertNotIn(forbidden, persisted)

    def test_cancel_uses_native_run_and_keeps_exact_conversation_link(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            client = FakeOpenDesign()
            service = DelegationService(payload(Path(temporary)), client=client)
            delegated = service.delegate({"brief": "Create it.", "idempotency_key": "cancel"})
            canceled = service.cancel(delegated["delegation"]["delegation_id"])
            self.assertEqual(canceled["delegation"]["status"], "canceled")
            self.assertIn("/conversations/", canceled["delegation"]["deep_link"])

    def test_workspace_scopes_produce_distinct_ids_and_stores(self) -> None:
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
            client = FakeOpenDesign()
            first = DelegationService(payload(Path(one), "alpha"), client=client).delegate({
                "brief": "Same explicit brief.",
                "idempotency_key": "same-key",
            })
            second = DelegationService(payload(Path(two), "beta"), client=client).delegate({
                "brief": "Same explicit brief.",
                "idempotency_key": "same-key",
            })
            self.assertNotEqual(
                first["delegation"]["delegation_id"],
                second["delegation"]["delegation_id"],
            )
            self.assertEqual(len(json.loads((Path(one) / "delegations/state.json").read_text())["delegations"]), 1)
            self.assertEqual(len(json.loads((Path(two) / "delegations/state.json").read_text())["delegations"]), 1)

    def test_state_degrades_only_delegation_when_public_api_is_unavailable(self) -> None:
        class Unavailable:
            def list_projects(self):
                raise OpenDesignUnavailable("offline")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            host = {"mode": "official-native", "state": "ready", "version": "0.16.1"}
            (root / "native-host-status.json").write_text(json.dumps(host), encoding="utf-8")
            state = SurfaceService(payload(root), client=Unavailable()).state()
            self.assertFalse(state["delegation_bridge"]["available"])
            self.assertEqual(state["host"]["state"], "ready")
            self.assertFalse(state["intercepts_native_routes"])
            self.assertEqual(json.loads((root / "native-host-status.json").read_text()), host)

    def test_state_projects_cli_diagnostics_from_native_profile_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "native-host-status.json").write_text(json.dumps({
                "schema_version": "1",
                "mode": "official-native",
                "state": "ready",
                "model_bridge": {
                    "state": "ready",
                    "semantic_enrichment": False,
                    "api": {"state": "ready", "protocol": "openai-compatible"},
                    "profiles": {
                        "state": "ready",
                        "cli": {
                            "state": "ready",
                            "profile_id": "installed-codex-cli",
                            "model_count": 7,
                        },
                    },
                },
            }), encoding="utf-8")

            state = SurfaceService(payload(root), client=FakeOpenDesign()).state()

        self.assertEqual(state["host"]["model_bridge"]["cli"], {
            "state": "ready",
            "profile_id": "installed-codex-cli",
            "model_count": 7,
        })

    def test_bridge_incompatibility_blocks_only_new_delegation_not_native_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "bridge-capabilities.json").write_text(json.dumps({
                "schema_version": "1",
                "model_access": {"state": "ready"},
                "delegation": {"state": "degraded", "reason": "public_api_contract_incompatible"},
            }), encoding="utf-8")
            service = SurfaceService(payload(root), client=FakeOpenDesign())

            state = service.state()
            self.assertFalse(state["delegation_bridge"]["available"])
            self.assertEqual(state["delegation_bridge"]["capability"]["state"], "degraded")
            self.assertEqual(state["native_data_owner"], "opendesign")
            with self.assertRaises(DelegationError) as raised:
                service.dispatch("delegate", {"brief": "Create it", "idempotency_key": "blocked"})
            self.assertEqual(raised.exception.code, "delegation_unavailable")

    def test_public_store_projection_rejects_poisoned_private_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identifier = "dlg_" + "a" * 32
            state_path = root / "delegations/state.json"
            state_path.parent.mkdir(parents=True)
            state_path.write_text(json.dumps({
                "schema_version": 1,
                "delegations": {
                    identifier: {
                        "delegation_id": identifier,
                        "status": "succeeded",
                        "od_project_id": "project_1",
                        "od_run_id": "run_1",
                        "deep_link": "file:///private/project",
                        "brief": "private brief",
                        "transcript": "private transcript",
                        "result_references": {
                            "run_id": "run_1",
                            "project": {"id": "project_1", "name": "Safe", "file_count": 1},
                            "artifacts": [{
                                "reference_id": "artifact-1",
                                "title": "Safe title",
                                "manifest": {"path": "/private"},
                                "body": "private artifact",
                            }],
                        },
                    }
                },
                "view_state": {"mode": "custom", "project_ids": ["../../private"]},
            }), encoding="utf-8")
            public = DelegationStore(str(root)).records()
            encoded = json.dumps(public)
            self.assertNotIn("private", encoded)
            self.assertNotIn("manifest", encoded)
            self.assertEqual(public[0]["deep_link"], "")

    def test_project_reference_projection_omits_native_private_fields(self) -> None:
        client = FakeOpenDesign()
        client.projects["od_project"] = {
            "id": "od_project",
            "name": "Safe title",
            "metadata": {"baseDir": "/private"},
            "resolvedDir": "/private",
            "status": {"value": "running", "runId": "private-run"},
            "createdAt": 1,
            "updatedAt": 2,
        }
        projects = ProjectSurfaces(client, "design-studio")
        results = projects.reference_search({"query": "safe", "limit": 10})["results"]
        encoded = json.dumps(results)
        self.assertEqual(results[0]["status"], "running")
        self.assertNotIn("baseDir", encoded)
        self.assertNotIn("resolvedDir", encoded)
        self.assertNotIn("private-run", encoded)

    def test_public_client_uses_only_exact_supported_broker_routes(self) -> None:
        class Response:
            status_code = 200

            def __init__(self, body: dict) -> None:
                self.body = body

            def json(self) -> dict:
                return self.body

        class Transport:
            def __init__(self) -> None:
                self.calls: list[tuple[str, str, dict]] = []

            def request(self, method: str, path: str, **kwargs):
                self.calls.append((method, path, kwargs))
                if path == "/api/projects":
                    return Response({"projects": []})
                if path.endswith("/messages"):
                    return Response({"messages": []})
                return Response({})

        transport = Transport()
        client = OpenDesignClient(payload(SimpleNamespace()), transport=transport)
        self.assertEqual(client.list_projects(), [])
        self.assertEqual(client.list_messages("project_1", "conversation_1"), [])
        self.assertEqual(
            [(method, path) for method, path, _ in transport.calls],
            [
                ("GET", "/api/projects"),
                ("GET", "/api/projects/project_1/conversations/conversation_1/messages"),
            ],
        )
        with self.assertRaises(ValueError):
            client.get_project("../../private")
        self.assertEqual(len(transport.calls), 2)

    def test_declared_tools_match_mcp_entrypoint_and_schemas(self) -> None:
        contract = json.loads((ROOT / "apps/design-studio/app_contract.json").read_text())
        schemas = json.loads((ROOT / "apps/design-studio/mcp/tool_schemas.json").read_text())
        from importlib.util import module_from_spec, spec_from_file_location

        spec = spec_from_file_location(
            "design_studio_mcp_server",
            ROOT / "apps/design-studio/mcp/server.py",
        )
        assert spec and spec.loader
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        declared = set(contract["capabilities"]["mcp_tools"])
        self.assertEqual(declared, set(schemas["tools"]))
        self.assertEqual(declared, set(module.TOOL_ACTIONS))

    def test_backend_cli_and_mcp_state_degrade_without_sidecar_capability(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            common = {
                "app_id": "design-studio",
                "workspace_id": "default",
                "data_root": temporary,
            }
            invocations = [
                (
                    ROOT / "apps/design-studio/backend/app_backend.py",
                    {**common, "body": {"action": "state"}},
                ),
                (
                    ROOT / "apps/design-studio/cli/app_cli.py",
                    {**common, "command_id": "design-studio", "arguments": {"action": "state"}},
                ),
                (
                    ROOT / "apps/design-studio/mcp/server.py",
                    {**common, "tool_name": "design_studio_state", "arguments": {}},
                ),
            ]
            for entrypoint, request in invocations:
                completed = subprocess.run(
                    [sys.executable, str(entrypoint)],
                    input=json.dumps(request),
                    text=True,
                    capture_output=True,
                    cwd=ROOT,
                    env={**os.environ, "PYTHONPATH": str(ROOT)},
                    check=True,
                )
                response = json.loads(completed.stdout)
                self.assertEqual(response["status_code"], 200, entrypoint)
                body = response.get("json", response)
                self.assertFalse(body["delegation_bridge"]["available"], entrypoint)
                self.assertFalse(body["intercepts_native_routes"], entrypoint)


if __name__ == "__main__":
    unittest.main()
