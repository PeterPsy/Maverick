"""Confined launch data for the disabled Gemini ACP integration."""

import os
from pathlib import Path
import shutil

from core.providers.models import RuntimeBackendLaunchSpec
from core.providers.native_acp_transport import NativeAcpError
from core.runtime.workspace_sandbox import build_bwrap_command


def gemini_acp_launch_spec(context, *, command, dependency_roots):
    session = context.session
    workspace = Path(session.workspace_root).resolve(strict=True)
    workdir = Path(session.workdir).resolve(strict=True)
    runtime = Path(session.runtime_root).resolve()
    if session.effective_mode != "sandbox" or not workdir.is_relative_to(workspace):
        raise NativeAcpError("native_acp_workspace_boundary_invalid")
    executable = shutil.which(command)
    if executable is None:
        raise NativeAcpError("native_runtime_not_installed")
    executable = str(Path(executable).resolve(strict=True))
    home = runtime / "gemini-home"
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    argv = [executable, "--acp"]
    if context.binding.model_id != "provider-default":
        argv.extend(["--model", context.binding.model_id])
    dependencies = [Path(executable).parent, *dependency_roots]
    sandboxed = build_bwrap_command(
        workspace_root=workspace, runtime_root=runtime, home_root=home,
        dependency_roots=dependencies, command=argv,
    )
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(home), "LANG": "C.UTF-8"}
    env.update({key: value for key, value in context.secret_env.items()
                if key in {"GEMINI_API_KEY", "GOOGLE_API_KEY"}})
    env["TMPDIR"] = str(runtime)
    return RuntimeBackendLaunchSpec(
        provider_id="gemini-cli", command=sandboxed, env_overrides=env,
        credential_binding_id=context.binding.credential_binding_id, resolved_secret_refs=[],
        working_directory=str(workdir), execution_mode="sandbox",
        readable_roots=[str(workspace), str(runtime), *map(os.fspath, dependencies)],
        writable_roots=[str(workspace), str(runtime)],
    )


__all__ = ["gemini_acp_launch_spec"]
