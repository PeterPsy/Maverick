"""The hosted sandbox must stay in its already-detached launcher's kill group."""

from dataclasses import replace
import os
from pathlib import Path
import subprocess
import time
from unittest import TestCase, mock
from uuid import uuid4

from core.runtime.hosted_tool_process_registry import HostedToolProcessRegistry
from core.runtime.process_control import runtime_processes_alive_for_session
from core.runtime.tool_core_capabilities import build_core_runtime_tool_capabilities
from tests.support.cases.full_workspace_contract import FullWorkspaceContractFixture


class HostedProcessSignalScopeTest(FullWorkspaceContractFixture, TestCase):
    def test_sandbox_child_stays_in_detached_launcher_group_until_interrupt(self):
        session = replace(self.harness.session, session_id=f"signal-scope-{uuid4().hex}")
        self.harness.store.insert_session(session)
        context = replace(self.context, session_id=session.session_id)
        registry = HostedToolProcessRegistry(store=self.harness.store)
        self.addCleanup(registry.terminate_session, session.session_id)
        capabilities = {surface.definition.handle: surface for surface in build_core_runtime_tool_capabilities(
            workspace_id=context.workspace_id, workspace_root=self.workspace,
            runtime_root=Path(session.runtime_root), process_registry=registry,
        )}
        started = capabilities["core-capability:process.start"].handler(
            {"argv": ["/bin/sh", "-c", "printf ready; read value"], "mutation_scopes": []}, context, None,
        )
        process_id = started.payload["process_id"]
        launcher = registry._live[process_id].process
        for _ in range(150):
            status = capabilities["core-capability:process.status"].handler({"process_id": process_id}, context, None)
            if status.payload["output"] == "ready":
                break
            time.sleep(0.01)
        self.assertEqual(status.payload["output"], "ready")
        processes = _marked_processes(session.session_id)
        self.assertGreaterEqual(len(processes), 2)
        self.assertEqual({process[0] for process in processes}, {launcher.pid})
        self.assertEqual({process[1] for process in processes}, {launcher.pid})
        self.assertEqual({process[2] for process in processes}, {0})
        self.assertNotEqual(os.getsid(0), launcher.pid)
        interrupted = capabilities["core-capability:process.interrupt"].handler({"process_id": process_id}, context, None)
        self.assertTrue(interrupted.payload["terminated"])
        self.assertFalse(runtime_processes_alive_for_session(session.session_id))

    def test_bounded_shell_also_detaches_before_bubblewrap_exec(self):
        with mock.patch("core.runtime.hosted_workspace_shell.subprocess.Popen", wraps=subprocess.Popen) as spawn:
            result = self._capabilities()["core-capability:shell.run"].handler(
                {"argv": ["/bin/sh", "-c", "printf confined"], "mutation_scopes": []}, self.context, None,
            )
        self.assertEqual(result["output"], "confined")
        self.assertTrue(spawn.call_args.kwargs["start_new_session"])
        self.assertNotIn("--new-session", spawn.call_args.args[0])


def _marked_processes(session_id):
    result = []
    for directory in Path("/proc").iterdir():
        if not directory.name.isdigit():
            continue
        try:
            environment = (directory / "environ").read_bytes().split(b"\0")
            if f"MAVERICK_RUNTIME_SESSION_ID={session_id}".encode() in environment:
                fields = (directory / "stat").read_text().rsplit(")", 1)[1].split()
                result.append(tuple(int(fields[index]) for index in (2, 3, 4)))  # pgid, sid, tty
        except OSError:
            continue
    return result
