"""Focused tests for Codex workspace-sandbox permission assumptions."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from core.providers.codex_app_server import _thread_params, _turn_permission_profile, _turn_sandbox_policy
from core.providers.models import RuntimeBackendLaunchSpec
from core.providers.provider_codex import CodexProviderAdapter
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.workspace_sandbox import build_bwrap_command


class CodexSandboxPermissionHypothesisTest(unittest.TestCase):
    def test_sandbox_turn_delegates_filesystem_to_external_sandbox(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace_root = Path(temp) / "workspaces" / "ceida"
            workspace_root.mkdir(parents=True)
            spec = _launch_spec(workspace_root)

            policy = _turn_sandbox_policy(spec)
            profile = _turn_permission_profile(spec)

        self.assertEqual(policy, {"type": "externalSandbox", "networkAccess": "enabled"})
        self.assertIsNone(profile)
        serialized = json.dumps(policy)
        self.assertNotIn("/bin/sh", serialized)
        self.assertNotIn("fileSystem", serialized)
        self.assertNotIn('"kind": "minimal"', serialized)

    @unittest.skipUnless(shutil.which("bwrap"), "bubblewrap is not installed")
    def test_workspace_sandbox_without_explicit_shell_dependency_cannot_execute_bin_sh(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace_root = Path(temp) / "workspaces" / "ceida"
            runtime_root = workspace_root / "runtime" / "sessions" / "sess-1"
            marker = workspace_root / "shell-ran.txt"
            workspace_root.mkdir(parents=True)
            command = build_bwrap_command(
                workspace_root=workspace_root,
                runtime_root=runtime_root,
                dependency_roots=[],
                dependency_files=[],
                command=["/bin/sh", "-c", "echo ok > shell-ran.txt"],
            )

            result = subprocess.run(command, text=True, capture_output=True, check=False)

        self.assertNotEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertFalse(marker.exists())

    @unittest.skipUnless(shutil.which("bwrap") and shutil.which("busybox"), "bubblewrap and static busybox are required")
    def test_workspace_sandbox_with_runtime_shell_dependency_can_execute_bin_sh(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace_root = Path(temp) / "workspaces" / "ceida"
            runtime_root = workspace_root / "runtime" / "sessions" / "sess-1"
            runtime_bin = runtime_root / "bin"
            marker = workspace_root / "shell-ran.txt"
            workspace_root.mkdir(parents=True)
            runtime_bin.mkdir(parents=True)
            runtime_shell = runtime_bin / "sh"
            shutil.copy2(Path(shutil.which("busybox") or ""), runtime_shell)
            runtime_shell.chmod(0o755)
            command = build_bwrap_command(
                workspace_root=workspace_root,
                runtime_root=runtime_root,
                dependency_roots=[],
                dependency_files=[(runtime_shell, Path("/bin/sh"))],
                command=["/bin/sh", "-c", "echo ok > shell-ran.txt"],
            )

            result = subprocess.run(command, text=True, capture_output=True, check=False)

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual(marker.read_text(encoding="utf-8").strip(), "ok")

    @unittest.skipUnless(shutil.which("bwrap") and shutil.which("busybox"), "bubblewrap and static busybox are required")
    def test_workspace_sandbox_does_not_expose_host_home_or_tmp_roots(self) -> None:
        with tempfile.TemporaryDirectory(dir="/home/ubuntu") as temp:
            workspace_root = Path(temp) / "maverick" / "workspaces" / "ceida"
            runtime_root = workspace_root / "runtime" / "sessions" / "sess-1"
            runtime_bin = runtime_root / "bin"
            workspace_root.mkdir(parents=True)
            runtime_bin.mkdir(parents=True)
            runtime_shell = runtime_bin / "sh"
            shutil.copy2(Path(shutil.which("busybox") or ""), runtime_shell)
            runtime_shell.chmod(0o755)
            command = build_bwrap_command(
                workspace_root=workspace_root,
                runtime_root=runtime_root,
                dependency_roots=[],
                dependency_files=[(runtime_shell, Path("/bin/sh"))],
                command=["/bin/sh", "-c", "ls -1 /"],
            )

            result = subprocess.run(command, text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        roots = set(result.stdout.splitlines())
        self.assertIn("workspace", roots)
        self.assertNotIn("home", roots)
        self.assertNotIn("tmp", roots)

    def test_sandbox_thread_start_should_not_describe_workspace_as_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace_root = Path(temp) / "workspaces" / "ceida"
            workspace_root.mkdir(parents=True)
            session = _session(workspace_root)

            params = _thread_params(session=session, launch_spec=_launch_spec(workspace_root))

        self.assertNotEqual(params["sandbox"], "read-only")

    def test_sandbox_launch_command_binds_runtime_shell_as_bin_sh(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace_root = root / "workspaces" / "ceida"
            runtime_root = workspace_root / "runtime" / "sessions" / "sess-1"
            runtime_bin = runtime_root / "bin"
            runtime_bin.mkdir(parents=True)
            runtime_shell = runtime_bin / "sh"
            runtime_shell.write_text("shell\n", encoding="utf-8")

            command = CodexProviderAdapter(codex_command="/usr/bin/codex")._build_command(
                workspace_root=workspace_root,
                runtime_root=runtime_root,
                runtime_bin=runtime_bin,
                execution_mode="sandbox",
                host_command="/usr/bin/codex",
            )

        self.assertIn("--dependency-file", command)
        self.assertIn(f"{runtime_shell}=/bin/sh", command)

    def test_prepare_runtime_bin_installs_static_busybox_as_runtime_shell(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace_root = root / "workspaces" / "ceida"
            workspace_root.mkdir(parents=True)
            source_shell = root / "busybox"
            source_shell.write_text("busybox\n", encoding="utf-8")
            source_shell.chmod(0o755)
            session = _session(workspace_root)
            adapter = CodexProviderAdapter(codex_command="/usr/bin/codex")

            with patch.object(adapter, "_static_busybox_binary", return_value=source_shell):
                runtime_bin = adapter._prepare_runtime_bin(session, host_command="/usr/bin/codex")

            runtime_shell = runtime_bin / "sh"
            self.assertEqual(runtime_shell.read_text(encoding="utf-8"), "busybox\n")
            self.assertTrue(runtime_shell.stat().st_mode & 0o111)


def _launch_spec(workspace_root: Path) -> RuntimeBackendLaunchSpec:
    return RuntimeBackendLaunchSpec(
        provider_id="codex",
        command=["codex", "app-server", "--listen", "stdio://"],
        env_overrides={},
        credential_binding_id=None,
        resolved_secret_refs=[],
        working_directory=str(workspace_root),
        execution_mode="sandbox",
        readable_roots=[str(workspace_root)],
        writable_roots=[str(workspace_root)],
    )


def _session(workspace_root: Path) -> RuntimeSessionRecord:
    now = datetime(2026, 5, 6, tzinfo=timezone.utc)
    return RuntimeSessionRecord(
        session_id="sess-1",
        workspace_id="ceida",
        agent_id="agent-1",
        status="created",
        requested_mode=None,
        effective_mode="sandbox",
        workspace_root=str(workspace_root),
        workdir=str(workspace_root),
        runtime_root=str(workspace_root / "runtime" / "sessions" / "sess-1"),
        started_at=now,
        updated_at=now,
        ended_at=None,
        last_progress_at=None,
    )


if __name__ == "__main__":
    unittest.main()
