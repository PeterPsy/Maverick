"""Runtime turn execution helpers."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess

from core.providers.models import ProviderDefinition
from core.runtime.runtime_session import RuntimeSessionRecord


@dataclass(frozen=True)
class RuntimeExecutionResult:
    """Result of one runtime turn execution."""

    output_text: str
    exit_code: int


def _codex_executable() -> str:
    configured = os.environ.get("MAVERICK3_CODEX_COMMAND", "").strip()
    if configured:
        return configured
    resolved = shutil.which("codex")
    if resolved:
        return resolved
    return "codex"


def _runtime_env(command_path: str) -> dict[str, str]:
    env = dict(os.environ)
    path_entries = [entry for entry in str(env.get("PATH") or "").split(os.pathsep) if entry]
    prepend: list[str] = []
    if os.sep in command_path:
        prepend.append(str(Path(command_path).parent))
    node = shutil.which("node")
    if node:
        prepend.append(str(Path(node).parent))
    merged: list[str] = []
    seen: set[str] = set()
    for entry in [*prepend, *path_entries]:
        if entry and entry not in seen:
            seen.add(entry)
            merged.append(entry)
    if merged:
        env["PATH"] = os.pathsep.join(merged)
    return env


def _codex_command(session: RuntimeSessionRecord, input_text: str, *, output_path: Path) -> list[str]:
    executable = _codex_executable()
    runtime_input = input_text
    if session.system_prompt:
        runtime_input = f"{session.system_prompt.strip()}\n\nUser task:\n{input_text}"
    command = [
        executable,
        "exec",
        "-C",
        session.workdir,
        "--color",
        "never",
        "--output-last-message",
        str(output_path),
    ]
    if session.effective_mode == "full-access":
        command.append("--dangerously-bypass-approvals-and-sandbox")
    else:
        command.append("--full-auto")
    command.append(runtime_input)
    return command


def execute_runtime_turn(
    *,
    session: RuntimeSessionRecord,
    provider: ProviderDefinition,
    input_text: str,
    timeout_seconds: int = 180,
    command_runner=subprocess.run,
) -> RuntimeExecutionResult:
    """Execute one turn through the selected provider.

    The initial v3 hosted runtime supports Codex as the only concrete provider.
    Other provider backends can implement the same boundary without changing the
    chat app or the HTTP runtime surface.
    """
    fake_response = os.environ.get("MAVERICK3_RUNTIME_FAKE_RESPONSE")
    if fake_response is not None:
        return RuntimeExecutionResult(output_text=fake_response, exit_code=0)

    if provider.provider_id != "codex":
        return RuntimeExecutionResult(
            output_text=f"Provider `{provider.provider_id}` is registered but has no executable adapter in this host yet.",
            exit_code=1,
        )

    Path(session.workdir).mkdir(parents=True, exist_ok=True)
    Path(session.runtime_root).mkdir(parents=True, exist_ok=True)
    output_path = Path(session.runtime_root) / "last-message.txt"
    if output_path.exists():
        output_path.unlink()
    process = command_runner(
        _codex_command(session, input_text, output_path=output_path),
        cwd=session.workdir,
        capture_output=True,
        env=_runtime_env(_codex_executable()),
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    stdout = output_path.read_text(encoding="utf-8").strip() if output_path.is_file() else str(process.stdout or "").strip()
    stderr = str(process.stderr or "").strip()
    output = stdout or stderr or "(Codex completed without output.)"
    if process.returncode != 0 and stderr and stdout:
        output = f"{stdout}\n\n{stderr}".strip()
    return RuntimeExecutionResult(output_text=output, exit_code=int(process.returncode or 0))


__all__ = ["RuntimeExecutionResult", "execute_runtime_turn"]
