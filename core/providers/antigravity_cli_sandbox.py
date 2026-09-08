"""Confined launch data for the Antigravity CLI native candidate."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import stat
import tempfile

from core.providers.models import RuntimeBackendLaunchSpec
from core.providers.native_structured_cli_transport import NativeStructuredCliError
from core.runtime.workspace_sandbox import build_bwrap_command


ANTIGRAVITY_DEFAULT_MODEL = "gemini-3.6-flash-high"
_ANTIGRAVITY_SETTINGS = {
    "enableTerminalSandbox": True,
    "modelProvider": "gemini",
    "toolPermission": "request-review",
}


def antigravity_stream_launch_spec(context, *, command: str, dependency_roots):
    """Build the exact machine-readable command without host-home inheritance."""
    session = context.session
    secret_env = getattr(context, "secret_env", None)
    provider_secret = (
        secret_env.get("MAVERICK_PROVIDER_SECRET")
        if isinstance(secret_env, dict)
        else None
    )
    if not isinstance(provider_secret, str) or not provider_secret.strip():
        raise NativeStructuredCliError("antigravity_credential_missing")
    workspace = Path(session.workspace_root).resolve(strict=True)
    workdir = Path(session.workdir).resolve(strict=True)
    runtime = Path(session.runtime_root).resolve(strict=False)
    if session.effective_mode != "sandbox" or workdir != workspace:
        raise NativeStructuredCliError("antigravity_workspace_boundary_invalid")
    executable = shutil.which(command)
    if executable is None:
        raise NativeStructuredCliError("native_runtime_not_installed")
    executable_path = Path(executable).resolve(strict=True)
    home = runtime / "antigravity-home"
    _private_directory(home, runtime)
    for relative in (".config", ".cache", ".local/share", ".local/state"):
        _private_directory(home / relative, runtime)
    _write_private_settings(home, runtime)
    log_path = runtime / "antigravity-cli.log"

    argv = [
        str(executable_path),
        "--input-format",
        "stream-json",
        "--output-format",
        "stream-json",
        "--sandbox",
        "--mode",
        "accept-edits",
        "--disable-slash-commands",
        "--print-timeout",
        "5m",
        "--log-file",
        str(log_path),
    ]
    model_id = str(context.binding.model_id or "").strip()
    if not model_id:
        raise NativeStructuredCliError("antigravity_model_missing")
    argv.extend(["--model", model_id])
    reasoning_effort = str(getattr(context.binding, "reasoning_effort", None) or "").strip()
    if reasoning_effort:
        if reasoning_effort not in {"low", "medium", "high"}:
            raise NativeStructuredCliError("antigravity_reasoning_effort_invalid")
        argv.extend(["--effort", reasoning_effort])

    dependencies = [executable_path.parent, *dependency_roots]
    sandboxed = build_bwrap_command(
        workspace_root=workspace,
        runtime_root=runtime,
        home_root=home,
        dependency_roots=dependencies,
        command=argv,
    )
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_DATA_HOME": str(home / ".local/share"),
        "XDG_STATE_HOME": str(home / ".local/state"),
        "LANG": "C.UTF-8",
        "GEMINI_API_KEY": provider_secret,
        "NO_COLOR": "1",
        "TMPDIR": str(runtime),
    }
    return RuntimeBackendLaunchSpec(
        provider_id="antigravity-cli",
        command=sandboxed,
        env_overrides=env,
        credential_binding_id=context.binding.credential_binding_id,
        resolved_secret_refs=[],
        working_directory=str(workdir),
        execution_mode="sandbox",
        readable_roots=[str(workspace), str(runtime), *map(os.fspath, dependencies)],
        writable_roots=[str(workspace), str(runtime)],
    )


def _write_private_settings(home: Path, runtime: Path) -> None:
    settings_root = home / ".gemini/antigravity-cli"
    _private_directory(settings_root, runtime)
    settings_path = settings_root / "settings.json"
    if settings_path.is_symlink():
        raise NativeStructuredCliError("antigravity_runtime_home_invalid")
    payload = (json.dumps(_ANTIGRAVITY_SETTINGS, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=settings_root,
            prefix=".settings-",
            mode="wb",
            delete=False,
        ) as stream:
            temporary_path = stream.name
            os.fchmod(stream.fileno(), 0o600)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, settings_path)
        temporary_path = None
        details = settings_path.stat(follow_symlinks=False)
        if not stat.S_ISREG(details.st_mode):
            raise NativeStructuredCliError("antigravity_runtime_home_invalid")
        settings_path.chmod(0o600, follow_symlinks=False)
    except NativeStructuredCliError:
        raise
    except OSError as error:
        raise NativeStructuredCliError(
            "antigravity_runtime_home_invalid"
        ) from error
    finally:
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass


def _private_directory(path: Path, runtime: Path) -> None:
    resolved_runtime = runtime.resolve(strict=False)
    if path.is_symlink() or not path.resolve(strict=False).is_relative_to(resolved_runtime):
        raise NativeStructuredCliError("antigravity_runtime_home_invalid")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or not path.is_dir():
        raise NativeStructuredCliError("antigravity_runtime_home_invalid")
    path.chmod(0o700)


__all__ = ["ANTIGRAVITY_DEFAULT_MODEL", "antigravity_stream_launch_spec"]
