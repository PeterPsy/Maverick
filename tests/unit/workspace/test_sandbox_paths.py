"""Tests for workspace-only runtime sandbox command construction."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from core.runtime.workspace_sandbox import _resolver_read_roots, build_bwrap_command


class WorkspaceSandboxTest(unittest.TestCase):
    def test_bwrap_command_mounts_workspace_without_mounting_repository_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo_root = Path(temp) / "maverick"
            workspace_root = repo_root / "workspaces" / "ceida"
            runtime_root = workspace_root / "runtime"
            dependency_root = Path(temp) / ".nvm"
            workspace_root.mkdir(parents=True)
            runtime_root.mkdir()
            dependency_root.mkdir()

            with patch("core.runtime.workspace_sandbox.shutil.which", return_value="/usr/bin/bwrap"):
                command = build_bwrap_command(
                    workspace_root=workspace_root,
                    runtime_root=runtime_root,
                    dependency_roots=[dependency_root],
                    dependency_files=[],
                    command=["codex", "app-server"],
                )

        self.assertIn("--bind", command)
        self.assertIn(str(workspace_root), command)
        self.assertIn("--ro-bind", command)
        self.assertIn(str(dependency_root), command)
        self.assertNotIn("/etc", _ro_bind_sources(command))
        self.assertTrue({"/usr", "/bin", "/lib", "/lib64"}.isdisjoint(_ro_bind_sources(command)))
        self.assertIn("--remount-ro", command)
        self.assertNotIn(str(repo_root), _mount_sources(command))
        self.assertNotIn(str(repo_root / "AGENTS.md"), command)
        self.assertEqual(command[-2:], ["codex", "app-server"])

    def test_resolver_roots_include_resolved_systemd_resolver_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_root = Path(temp)
            etc = temp_root / "etc"
            resolver = temp_root / "run" / "systemd" / "resolve"
            etc.mkdir()
            resolver.mkdir(parents=True)
            target = resolver / "stub-resolv.conf"
            target.write_text("nameserver 127.0.0.53\n", encoding="utf-8")
            resolv_conf = etc / "resolv.conf"
            resolv_conf.symlink_to("../run/systemd/resolve/stub-resolv.conf")

            roots = _resolver_read_roots(resolv_conf)

        self.assertEqual(roots, [resolver])

    @unittest.skipUnless(shutil.which("bwrap"), "bubblewrap is not installed")
    def test_bwrap_command_denies_writes_outside_workspace_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo_root = Path(temp) / "maverick"
            workspace_root = repo_root / "workspaces" / "ceida"
            runtime_root = workspace_root / ".runtime"
            workspace_root.mkdir(parents=True)
            command = build_bwrap_command(
                workspace_root=workspace_root,
                runtime_root=runtime_root,
                dependency_roots=_shell_dependency_roots(),
                dependency_files=[],
                command=[
                    _shell_command(),
                    "-c",
                    (
                        "set -eu; "
                        "echo ok > workspace-write.txt; "
                        f"if echo bad > {repo_root / 'outside-write.txt'} 2>/dev/null; "
                        "then exit 42; fi; "
                        "if echo bad > /outside-write.txt 2>/dev/null; "
                        "then exit 43; fi; "
                        "if mkdir -p /run && echo bad > /run/outside-write.txt 2>/dev/null; "
                        "then exit 44; fi; "
                        "test -f workspace-write.txt"
                    ),
                ],
            )

            result = subprocess.run(command, text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    @unittest.skipUnless(shutil.which("bwrap"), "bubblewrap is not installed")
    def test_bwrap_command_binds_dependency_file_to_runtime_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo_root = Path(temp) / "maverick"
            workspace_root = repo_root / "workspaces" / "ceida"
            runtime_root = workspace_root / ".runtime"
            host_tool = Path(temp) / "host-tool"
            workspace_root.mkdir(parents=True)
            host_tool.write_text(f"#!{_shell_command()}\necho tool-ok\n", encoding="utf-8")
            host_tool.chmod(0o755)
            sandbox_tool = runtime_root / "bin" / "host-tool"
            command = build_bwrap_command(
                workspace_root=workspace_root,
                runtime_root=runtime_root,
                dependency_roots=_shell_dependency_roots(),
                dependency_files=[(host_tool, sandbox_tool)],
                command=[str(sandbox_tool)],
            )

            result = subprocess.run(command, text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(result.stdout.strip(), "tool-ok")

    @unittest.skipUnless(shutil.which("bwrap") and shutil.which("rg"), "bubblewrap and rg are required")
    def test_bwrap_command_allows_bound_rg_inside_workspace_without_outside_reads(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo_root = Path(temp) / "maverick"
            workspace_root = repo_root / "workspaces" / "ceida"
            runtime_root = workspace_root / ".runtime"
            runtime_bin = runtime_root / "bin"
            outside_file = repo_root / "AGENTS.md"
            workspace_root.mkdir(parents=True)
            outside_file.parent.mkdir(parents=True, exist_ok=True)
            outside_file.write_text("outside-only-needle\n", encoding="utf-8")
            (workspace_root / "notes.txt").write_text("workspace-only-needle\n", encoding="utf-8")
            host_rg = Path(shutil.which("rg") or "").resolve(strict=False)
            command = build_bwrap_command(
                workspace_root=workspace_root,
                runtime_root=runtime_root,
                dependency_roots=_shell_dependency_roots(),
                dependency_files=[(host_rg, runtime_bin / "rg")],
                command=[
                    _shell_command(),
                    "-c",
                    (
                        "set -eu; "
                        "command -v rg; "
                        "rg workspace-only-needle .; "
                        f"if rg outside-only-needle {outside_file} 2>/dev/null; then exit 42; fi"
                    ),
                ],
            )

            result = subprocess.run(command, text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("notes.txt", result.stdout)
        self.assertIn("workspace-only-needle", result.stdout)

    @unittest.skipUnless(shutil.which("bwrap"), "bubblewrap is not installed")
    def test_bwrap_command_masks_system_document_roots_without_breaking_shell(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo_root = Path(temp) / "maverick"
            workspace_root = repo_root / "workspaces" / "ceida"
            runtime_root = workspace_root / ".runtime"
            workspace_root.mkdir(parents=True)
            command = build_bwrap_command(
                workspace_root=workspace_root,
                runtime_root=runtime_root,
                dependency_roots=_shell_dependency_roots(),
                dependency_files=[],
                command=[
                    _shell_command(),
                    "-c",
                    (
                        "set -eu; "
                        f"{_shell_command()} -c true; "
                        "if [ -e /usr/share/doc ]; then exit 45; fi; "
                        "if [ -e /usr/local/share/doc ]; then exit 46; fi"
                    ),
                ],
            )

            result = subprocess.run(command, text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)


def _mount_sources(command: list[str]) -> list[str]:
    sources: list[str] = []
    for index, item in enumerate(command[:-2]):
        if item in {"--bind", "--ro-bind"}:
            sources.append(command[index + 1])
    return sources


def _ro_bind_sources(command: list[str]) -> list[str]:
    sources: list[str] = []
    for index, item in enumerate(command[:-2]):
        if item == "--ro-bind":
            sources.append(command[index + 1])
    return sources


def _shell_dependency_roots() -> list[Path]:
    return [path for path in [Path("/bin"), Path("/lib"), Path("/lib64"), Path("/usr")] if path.exists()]


def _shell_command() -> str:
    return str(Path(shutil.which("sh") or "/bin/sh").resolve(strict=False))


if __name__ == "__main__":
    unittest.main()
