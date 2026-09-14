from __future__ import annotations

import shutil
from types import SimpleNamespace
import time
import unittest

from core.providers.agentic_models import (
    codex_runtime_capabilities,
    codex_runtime_policy,
)
from core.providers.openrouter_agentic_profile import (
    openrouter_agentic_capabilities,
    openrouter_agentic_preview_policy,
)
from core.runtime.hosted_tool_process_registry import HostedToolProcessRegistry
from core.runtime.lifecycle_service_sessions import create_runtime_session
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.runtime.tool_core_capabilities import build_core_runtime_tool_capabilities
from tests.support.collections import FakeCollection
from tests.support.repo import make_temp_repo_root


class AgenticFullAccessParityTest(unittest.TestCase):
    def test_codex_and_openrouter_declare_the_same_operational_capabilities(self) -> None:
        codex = codex_runtime_capabilities()
        openrouter = openrouter_agentic_capabilities()
        for name in (
            "streaming",
            "tool_orchestration",
            "cli",
            "mcp",
            "skill_catalog",
            "filesystem_list",
            "filesystem_read",
            "filesystem_write",
            "shell",
            "interrupt",
            "recovery",
            "app_references",
        ):
            with self.subTest(capability=name):
                self.assertTrue(getattr(codex, name))
                self.assertTrue(getattr(openrouter, name))
        codex_policy = codex_runtime_policy()
        openrouter_policy = openrouter_agentic_preview_policy()
        self.assertEqual(
            codex_policy.allowed_surface_kinds,
            openrouter_policy.allowed_surface_kinds,
        )
        self.assertEqual(
            codex_policy.tool_handle_mode,
            openrouter_policy.tool_handle_mode,
        )
        self.assertFalse(codex_policy.require_confirmation_for_mutating)
        self.assertFalse(openrouter_policy.require_confirmation_for_mutating)

    def test_hosted_full_access_supports_files_shell_and_managed_processes(self) -> None:
        root = make_temp_repo_root(self)
        workspace = root / "workspaces" / "default"
        outside = root / "outside"
        runtime = workspace / "runtime"
        workspace.mkdir()
        outside.mkdir()
        try:
            (workspace / ".git").mkdir()
            (workspace / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
            external = outside / "external.txt"
            external.write_text("outside marker\n", encoding="utf-8")
            store = _runtime_store()
            create_runtime_session(
                store,
                session_id="session-parity",
                workspace_id="default",
                agent_id="chat",
                start_path=workspace,
            )
            registry = HostedToolProcessRegistry(store=store)
            surfaces = {
                item.definition.handle: item
                for item in build_core_runtime_tool_capabilities(
                    workspace_id="default",
                    workspace_root=workspace,
                    runtime_root=runtime,
                    process_registry=registry,
                    execution_mode="full-access",
                )
            }
            self.assertTrue(
                {
                    "core-capability:filesystem.list",
                    "core-capability:filesystem.search",
                    "core-capability:filesystem.read",
                    "core-capability:filesystem.write",
                    "core-capability:filesystem.edit",
                    "core-capability:filesystem.patch",
                    "core-capability:filesystem.move",
                    "core-capability:filesystem.delete",
                    "core-capability:shell.run",
                    "core-capability:process.start",
                    "core-capability:process.status",
                    "core-capability:process.input",
                    "core-capability:process.interrupt",
                }.issubset(surfaces)
            )
            context = SimpleNamespace(
                workspace_id="default",
                session_id="session-parity",
                execution_mode="full-access",
                execution_control=None,
            )

            listing = surfaces["core-capability:filesystem.list"].handler(
                {"path": ".", "max_depth": 2, "max_results": 100}, context, None
            )
            self.assertIn(
                str(workspace / ".git" / "HEAD"),
                {item["path"] for item in listing.payload["entries"]},
            )
            reading = surfaces["core-capability:filesystem.read"].handler(
                {"path": str(external)}, context, None
            )
            self.assertEqual(reading.payload["content"], "outside marker\n")
            workspace_uri_read = surfaces[
                "core-capability:filesystem.read"
            ].handler(
                {"path": "workspace://default/.git/HEAD"},
                context,
                None,
            )
            self.assertEqual(
                workspace_uri_read.payload["content"],
                "ref: refs/heads/main\n",
            )
            search = surfaces["core-capability:filesystem.search"].handler(
                {"path": str(outside), "query": "marker"}, context, None
            )
            self.assertEqual(search.payload["result_count"], 1)

            written = outside / "written.txt"
            surfaces["core-capability:filesystem.write"].handler(
                {"path": str(written), "content": "before"}, context, None
            )
            surfaces["core-capability:filesystem.edit"].handler(
                {"path": str(written), "old_text": "before", "new_text": "after"},
                context,
                None,
            )
            surfaces["core-capability:filesystem.patch"].handler(
                {
                    "path": str(written),
                    "operations": [
                        {"old_text": "after", "new_text": "patched"}
                    ],
                },
                context,
                None,
            )
            moved = outside / "moved.txt"
            surfaces["core-capability:filesystem.move"].handler(
                {
                    "source_path": str(written),
                    "destination_path": str(moved),
                },
                context,
                None,
            )
            self.assertEqual(moved.read_text(encoding="utf-8"), "patched")
            surfaces["core-capability:filesystem.delete"].handler(
                {"path": str(moved)}, context, None
            )
            self.assertFalse(moved.exists())

            required_cli = ("git", "rg")
            for name in required_cli:
                self.assertIsNotNone(shutil.which(name), f"missing required CLI: {name}")
            shell = surfaces["core-capability:shell.run"].handler(
                {
                    "argv": [
                        "/bin/sh",
                        "-c",
                        "; ".join(
                            [
                                *(
                                    f"printf 'cli:{name}\\n'; {name} --version"
                                    for name in required_cli
                                ),
                                "printf 'workspace:%s mode:%s\\n' "
                                '"$MAVERICK_WORKSPACE_ID" '
                                '"$MAVERICK_EFFECTIVE_MODE"',
                            ]
                        ),
                    ],
                    "cwd": str(outside),
                },
                context,
                None,
            )
            self.assertEqual(shell["exit_code"], 0)
            for name in required_cli:
                self.assertIn(f"cli:{name}", shell["output"].lower())
            self.assertIn("workspace:default mode:full-access", shell["output"])

            started = surfaces["core-capability:process.start"].handler(
                {
                    "argv": ["/bin/sh", "-c", "read line; printf 'received:%s' \"$line\""],
                    "cwd": str(outside),
                },
                context,
                None,
            ).payload
            process_id = str(started["process_id"])
            surfaces["core-capability:process.input"].handler(
                {"process_id": process_id, "content": "hello\n", "close": True},
                context,
                None,
            )
            status = None
            for _attempt in range(100):
                status = surfaces["core-capability:process.status"].handler(
                    {"process_id": process_id}, context, None
                ).payload
                if status["status"] != "running":
                    break
                time.sleep(0.01)
            self.assertIsNotNone(status)
            self.assertEqual(status["status"], "exited")
            self.assertIn("received:hello", status["output"])

            sleeping = surfaces["core-capability:process.start"].handler(
                {"argv": ["/bin/sh", "-c", "sleep 30"], "cwd": str(outside)},
                context,
                None,
            ).payload
            interrupted = surfaces[
                "core-capability:process.interrupt"
            ].handler(
                {"process_id": str(sleeping["process_id"])},
                context,
                None,
            ).payload
            self.assertTrue(interrupted["terminated"])
            self.assertEqual(interrupted["status"], "terminated")
        finally:
            registry.terminate_session("session-parity")


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
