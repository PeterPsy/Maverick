"""Codex runtime backend adapter."""

from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path
import shlex
import shutil
import sys
from typing import TYPE_CHECKING

from core.providers.models import ProviderCapabilitySet, ProviderDefinition, ProviderModelOption, ProviderReasoningOption
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.workspace_api_token import issue_workspace_api_token

if TYPE_CHECKING:
    from core.runtime.execution import RuntimeExecutionResult
    from core.skills.models import SkillDefinition, SkillMaterialization

CODEX_RUNTIME_HOME_FILES = ("auth.json", "version.json", ".personality_migration", "installation_id")
CODEX_DISABLED_RUNTIME_FEATURES = ("apps", "plugins")
CODEX_SYSTEM_SKILLS_ROOT = ".system"
CODEX_DEFAULT_MODEL = "gpt-5.5"
CODEX_DEFAULT_REASONING_EFFORT = "high"
CODEX_MANAGED_TOP_LEVEL_CONFIG_KEYS = {"model", "model_reasoning_effort"}
CODEX_MANAGED_RUNTIME_FEATURES = {
    "apps": False,
    "plugins": False,
    "skill_mcp_dependency_install": False,
}


def utcnow() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(tz=UTC)


def _codex_executable() -> str:
    configured = os.environ.get("MAVERICK_CODEX_COMMAND", "").strip()
    if configured:
        return configured
    resolved = shutil.which("codex")
    if resolved:
        return resolved
    return "codex"


def _codex_app_server_command(*, execution_mode: str, codex_command: str | None = None) -> list[str]:
    """Return the canonical Codex app-server command for interactive sessions."""
    command = [str(codex_command or "").strip() or _codex_executable()]
    command.extend(["app-server", "--listen", "stdio://"])
    return command


def build_codex_definition(
    now: datetime | None = None,
    *,
    model_options: list[ProviderModelOption] | None = None,
    default_model_id: str | None = None,
) -> ProviderDefinition:
    """Build the canonical provider definition for the local Codex backend."""
    timestamp = now or utcnow()
    options = list(model_options or _fallback_model_options())
    return ProviderDefinition(
        provider_id="codex",
        label="Codex",
        description="Local Codex runtime backend for interactive agent execution.",
        kind="runtime_backend",
        status="active",
        capabilities=ProviderCapabilitySet(
            supports_interactive_runtime=True,
            supports_streaming=True,
            supports_tools=True,
            supports_mcp=True,
            supports_skills=True,
            supports_filesystem_access=True,
            supports_remote_execution=False,
            supports_api_key_auth=False,
            supports_local_binary=True,
        ),
        default_model_family=default_model_id or _default_model_id(options),
        requires_credentials=False,
        supported_execution_modes=["sandbox", "full-access"],
        created_at=timestamp,
        updated_at=timestamp,
        model_options=options,
    )


def _fallback_model_options() -> list[ProviderModelOption]:
    return [
        ProviderModelOption(
            model_id=CODEX_DEFAULT_MODEL,
            label=CODEX_DEFAULT_MODEL,
            description="Default Codex model configured by Maverick when the Codex model catalog cannot be read.",
            default_reasoning_effort=CODEX_DEFAULT_REASONING_EFFORT,
            supported_reasoning_efforts=_fallback_reasoning_options(),
        )
    ]


def _fallback_reasoning_options() -> list[ProviderReasoningOption]:
    return [
        ProviderReasoningOption(effort="low", label="Low", description="Fast responses with lighter reasoning"),
        ProviderReasoningOption(effort="medium", label="Mid", description="Balanced reasoning depth"),
        ProviderReasoningOption(effort="high", label="High", description="Greater reasoning depth"),
        ProviderReasoningOption(effort="xhigh", label="Extra high", description="Maximum reasoning depth"),
    ]


def _default_model_id(options: list[ProviderModelOption]) -> str:
    option_ids = [option.model_id for option in options]
    if CODEX_DEFAULT_MODEL in option_ids:
        return CODEX_DEFAULT_MODEL
    return option_ids[0] if option_ids else CODEX_DEFAULT_MODEL


def _default_reasoning_effort(option: ProviderModelOption | None) -> str | None:
    if option is None:
        return CODEX_DEFAULT_REASONING_EFFORT
    supported = {reasoning.effort for reasoning in option.supported_reasoning_efforts}
    if option.default_reasoning_effort in supported:
        return option.default_reasoning_effort
    if CODEX_DEFAULT_REASONING_EFFORT in supported:
        return CODEX_DEFAULT_REASONING_EFFORT
    return option.supported_reasoning_efforts[0].effort if option.supported_reasoning_efforts else None




class CodexCommandMixin:
    def build_recovery_command(
        self,
        *,
        repository_root: Path,
        model_id: str | None = None,
        model_reasoning_effort: str | None = None,
        command_override: str | None = None,
    ) -> list[str]:
        """Build a one-shot full-access Codex command for backend rescue."""
        self.validate_backend()
        selected_model, selected_reasoning = self.validate_model_settings(model_id, model_reasoning_effort)
        override = str(command_override or "").strip()
        if override:
            return shlex.split(override)
        command = [
            self._runtime_command(self.codex_command),
            "exec",
            "--dangerously-bypass-approvals-and-sandbox",
            "--json",
            "--skip-git-repo-check",
            "-C",
            str(repository_root),
            "-m",
            selected_model,
        ]
        if selected_reasoning:
            command.extend(["-c", f"model_reasoning_effort={selected_reasoning!r}"])
        command.append("-")
        return command



    def _build_command(
        self,
        *,
        workspace_root: Path,
        runtime_root: Path,
        runtime_bin: Path | None = None,
        execution_mode: str,
        host_command: str | None = None,
    ) -> list[str]:
        host_command = host_command or self._runtime_command(self.codex_command)
        command = [host_command]
        for feature in CODEX_DISABLED_RUNTIME_FEATURES:
            command.extend(["--disable", feature])
        command.extend(self.server_args)
        if execution_mode == "full-access":
            return command
        sandbox_launcher = (runtime_bin or runtime_root / "bin") / "workspace_sandbox.py"
        dependency_args = self._dependency_root_args(host_command)
        host_command_path = Path(host_command)
        if self._is_standalone_codex_binary(host_command_path):
            sandbox_command = runtime_root / "bin" / "codex"
            dependency_args = ["--dependency-file", f"{host_command_path}={sandbox_command}"]
            command[0] = str(sandbox_command)
            rg = self._vendored_codex_tool_binary(host_command_path, "rg")
            if rg is not None:
                dependency_args.extend(["--dependency-file", f"{rg}={runtime_root / 'bin' / 'rg'}"])
        return [
            sys.executable,
            str(sandbox_launcher),
            "--workspace-root",
            str(workspace_root),
            "--runtime-root",
            str(runtime_root),
            *dependency_args,
            "--",
            *command,
        ]



    def _build_subprocess_env(
        self,
        *,
        workdir: Path,
        workspace_root: Path,
        runtime_root: Path,
        runtime_home: Path,
        runtime_bin: Path,
        session: RuntimeSessionRecord,
        execution_mode: str,
        secret_env: dict[str, str] | None = None,
        base_env: dict[str, str] | None = None,
    ) -> dict[str, str]:
        env = dict(base_env or os.environ)
        env.update(secret_env or {})
        path_entries = [entry for entry in str(env.get("PATH") or "").split(os.pathsep) if entry]
        prepend_entries: list[str] = [str(runtime_bin)]

        if os.sep in self.codex_command:
            configured = Path(self.codex_command).expanduser()
            prepend_entries.append(str(configured.parent))
        else:
            resolved = shutil.which(self.codex_command, path=os.pathsep.join(path_entries)) or shutil.which(self.codex_command)
            if resolved:
                prepend_entries.append(str(Path(resolved).resolve().parent))

        resolved_node = shutil.which("node", path=os.pathsep.join(path_entries)) or shutil.which("node")
        if resolved_node:
            prepend_entries.append(str(Path(resolved_node).resolve().parent))

        merged_path: list[str] = []
        seen: set[str] = set()
        for entry in [*prepend_entries, *path_entries]:
            normalized = str(entry or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            merged_path.append(normalized)
        if merged_path:
            env["PATH"] = os.pathsep.join(merged_path)

        env["CODEX_HOME"] = str(runtime_home)
        env["MAVERICK_WORKSPACE_ROOT"] = str(workspace_root)
        env["MAVERICK_WORKSPACE_ID"] = session.workspace_id
        env["MAVERICK_RUNTIME_ROOT"] = str(runtime_root)
        env["MAVERICK_RUNTIME_BIN"] = str(runtime_bin)
        env["MAVERICK_RUNTIME_SESSION_ID"] = session.session_id
        env["MAVERICK_EFFECTIVE_MODE"] = execution_mode
        env["MAVERICK_RUNTIME_API_TOKEN"] = issue_workspace_api_token(
            workspace_id=session.workspace_id,
            runtime_session_id=session.session_id,
            effective_mode=execution_mode,
        )
        env["MAVERICK_API_BASE"] = str(env.get("MAVERICK_API_BASE") or "http://127.0.0.1:8014").rstrip("/")
        if execution_mode == "sandbox":
            runtime_root.mkdir(parents=True, exist_ok=True)
            env["TMPDIR"] = str(runtime_root)
            env["TMP"] = str(runtime_root)
            env["TEMP"] = str(runtime_root)
            env["HOME"] = str(runtime_home)
            env.pop("PYTHONPATH", None)
        return env
