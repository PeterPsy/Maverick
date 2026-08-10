"""Backend, CLI, and MCP parity for declared project editing surfaces."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


APP_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = APP_ROOT.parents[1]
FIXTURE = APP_ROOT / "tests" / "fixtures" / "project-ir-v1-golden.json"


def invoke(relative_path: str, payload: dict) -> dict:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(REPOSITORY_ROOT)
    result = subprocess.run(
        [sys.executable, str(APP_ROOT / relative_path)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
        env=environment,
        cwd=APP_ROOT,
        timeout=30,
    )
    if result.returncode:
        raise AssertionError(result.stderr or result.stdout)
    return json.loads(result.stdout)


def batch(revision_id: str, batch_id: str, operation: dict) -> dict:
    return {
        "workspace_id": "workspace-test",
        "project_id": "project-golden",
        "base_revision_id": revision_id,
        "operation_batch_id": batch_id,
        "preconditions": [{"type": "head_is", "revision_id": revision_id}],
        "actor": {"kind": "system", "id": "payload-spoof"},
        "operations": [operation],
        "autosave": {"enabled": False, "reason": "surface-test"},
        "metadata": {"message": "Surface parity"},
    }


class ProjectSurfaceParityTest(unittest.TestCase):
    def test_project_reads_and_idempotent_mutation_match_all_surfaces(self) -> None:
        with TemporaryDirectory() as temp_dir:
            base = self._base(temp_dir)
            created = self._create(base)
            revision_id = created["project"]["head_revision_id"]

            backend_list = invoke("backend/app_backend.py", {**base, "body": {"action": "project.list"}})["json"]
            cli_list = invoke("cli/app_cli.py", {**base, "command_id": "video-studio.video-studio", "arguments": {"action": "project.list"}})
            mcp_list = invoke("mcp/server.py", {**base, "tool_name": "video_studio_project_list", "arguments": {}})
            self.assertEqual(backend_list["projects"], cli_list["projects"])
            self.assertEqual(cli_list["projects"], mcp_list["projects"])

            request = batch(revision_id, "batch-parity", {"type": "project.rename", "name": "Surface edited"})
            backend = invoke("backend/app_backend.py", {**base, "body": {"action": "operations.apply", "batch": request}})
            cli = invoke("cli/app_cli.py", {**base, "command_id": "video-studio.video-studio", "arguments": {"action": "operations.apply", "batch": request}})
            mcp = invoke("mcp/server.py", {**base, "tool_name": "video_studio_operations_apply", "arguments": {"batch": request}})
            self.assertEqual(backend["json"]["revision"], cli["revision"])
            self.assertEqual(cli["revision"], mcp["revision"])
            self.assertEqual(
                {event["resource"] for event in backend["app_events"]},
                {"project-metadata", "revisions"},
            )
            audit = invoke(
                "mcp/server.py",
                {
                    **base,
                    "tool_name": "video_studio_revision_get",
                    "arguments": {
                        "project_id": "project-golden",
                        "revision_id": backend["json"]["revision"]["revision_id"],
                    },
                },
            )
            self.assertEqual(audit["revision"]["actor"], {"kind": "user", "id": "trusted-editor"})

            project_id = created["project"]["project_id"]
            arguments = {"action": "project.get", "project_id": project_id}
            backend_get = invoke("backend/app_backend.py", {**base, "body": arguments})["json"]
            cli_get = invoke("cli/app_cli.py", {**base, "command_id": "video-studio.video-studio", "arguments": arguments})
            mcp_get = invoke("mcp/server.py", {**base, "tool_name": "video_studio_project_get", "arguments": {"project_id": project_id}})
            self.assertEqual(backend_get["project"], cli_get["project"])
            self.assertEqual(cli_get["project"], mcp_get["project"])

    def test_every_declared_project_surface_executes_real_service_behavior(self) -> None:
        with TemporaryDirectory() as temp_dir, TemporaryDirectory() as import_dir:
            base = self._base(temp_dir)
            created = self._create(base)["project"]
            initial = created["head_revision_id"]
            renamed = invoke(
                "mcp/server.py",
                {
                    **base,
                    "tool_name": "video_studio_project_rename",
                    "arguments": {
                        "project_id": "project-golden", "name": "Renamed", "base_revision_id": initial,
                        "operation_batch_id": "batch-rename",
                    },
                },
            )["revision"]
            revision = invoke("cli/app_cli.py", {**base, "command_id": "video-studio.video-studio", "arguments": {"action": "revision.get", "project_id": "project-golden", "revision_id": renamed["revision_id"]}})
            self.assertEqual(revision["revision"]["digest"], renamed["digest"])
            comparison = invoke("mcp/server.py", {**base, "tool_name": "video_studio_revision_compare", "arguments": {"project_id": "project-golden", "before_revision_id": initial, "after_revision_id": renamed["revision_id"]}})
            self.assertEqual(comparison["comparison"]["change_count"], 1)

            undo_request = batch(renamed["revision_id"], "batch-undo", {"type": "history.undo"})
            undone = invoke("backend/app_backend.py", {**base, "body": {"action": "history.undo", "batch": undo_request}})["json"]["revision"]
            redo_request = batch(undone["revision_id"], "batch-redo", {"type": "history.redo"})
            redone = invoke(
                "cli/app_cli.py",
                {**base, "command_id": "video-studio.video-studio", "arguments": {"action": "history.redo", "batch": redo_request}},
            )["revision"]
            self.assertEqual(redone["revision_id"], renamed["revision_id"])

            duplicate = invoke("mcp/server.py", {**base, "tool_name": "video_studio_project_duplicate", "arguments": {"project_id": "project-golden", "new_project_id": "project-copy", "name": "Copy"}})["project"]
            self.assertEqual(duplicate["project_id"], "project-copy")
            archived = invoke("cli/app_cli.py", {**base, "command_id": "video-studio.video-studio", "arguments": {"action": "project.archive", "project_id": "project-copy"}})["project"]
            self.assertIsNotNone(archived["archived_at"])
            restored = invoke("backend/app_backend.py", {**base, "body": {"action": "project.restore", "project_id": "project-copy"}})["json"]["project"]
            self.assertIsNone(restored["archived_at"])

            exported = invoke("mcp/server.py", {**base, "tool_name": "video_studio_native_export", "arguments": {"project_id": "project-golden"}})["native_project"]
            import_base = self._base(import_dir)
            imported = invoke("mcp/server.py", {**import_base, "tool_name": "video_studio_native_import", "arguments": {"native_project": exported}})["project"]
            self.assertEqual(imported["project_ir"], exported["revision"]["project_ir"])

    def test_surface_errors_share_stable_code_path_message_and_details(self) -> None:
        with TemporaryDirectory() as temp_dir:
            base = self._base(temp_dir)
            body = {"action": "project.get", "project_id": "missing"}
            backend = invoke("backend/app_backend.py", {**base, "body": body})["json"]["error"]
            cli = invoke("cli/app_cli.py", {**base, "command_id": "video-studio.video-studio", "arguments": body})["error"]
            mcp = invoke("mcp/server.py", {**base, "tool_name": "video_studio_project_get", "arguments": {"project_id": "missing"}})["error"]
            self.assertEqual(backend, cli)
            self.assertEqual(cli, mcp)
            self.assertEqual(set(backend), {"code", "path", "message", "details"})

    def test_transport_actor_fields_are_not_part_of_the_public_request_contract(self) -> None:
        with TemporaryDirectory() as temp_dir:
            base = self._base(temp_dir)
            request = {
                "action": "project.create",
                "name": "Spoofed",
                "actor": {"kind": "system", "id": "attacker"},
            }
            backend = invoke("backend/app_backend.py", {**base, "body": request})["json"]["error"]
            cli = invoke(
                "cli/app_cli.py",
                {**base, "command_id": "video-studio.video-studio", "arguments": request},
            )["error"]
            mcp = invoke(
                "mcp/server.py",
                {
                    **base,
                    "tool_name": "video_studio_project_create",
                    "arguments": {"name": "Spoofed", "actor": request["actor"]},
                },
            )["error"]
            self.assertEqual(backend, cli)
            self.assertEqual(cli, mcp)
            self.assertEqual(backend["code"], "request_shape_invalid")

    @staticmethod
    def _base(temp_dir: str) -> dict:
        return {
            "app_id": "video-studio",
            "workspace_id": "workspace-test",
            "user_id": "trusted-editor",
            "data_root": str(Path(temp_dir) / "video-studio"),
        }

    @staticmethod
    def _create(base: dict) -> dict:
        document = json.loads(FIXTURE.read_text(encoding="utf-8"))
        result = invoke(
            "backend/app_backend.py",
            {
                **base,
                "body": {
                    "action": "project.create", "project_id": "project-golden", "name": "Golden timeline",
                    "project_ir": document,
                },
            },
        )
        if result["status_code"] != 200:
            raise AssertionError(result)
        self_events = {event["resource"] for event in result["app_events"]}
        if self_events != {"projects", "revisions"}:
            raise AssertionError(self_events)
        return result["json"]


if __name__ == "__main__":
    unittest.main()
