"""Codex runtime backend adapter."""

from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path
import shutil
import subprocess
from typing import TYPE_CHECKING, Callable

from core.providers.errors import ProviderLaunchError
from core.providers.models import (
    ProviderCapabilitySet,
    ProviderDefinition,
    ProviderModelOption,
    ProviderReasoningOption,
    RuntimeBackendLaunchSpec,
)
from core.runtime.execution_events import RuntimeExecutionEventSink
from core.runtime.runtime_session import RuntimeSessionRecord

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




class CodexLaunchMixin:
    def validate_backend(self) -> None:
        """Ensure the configured Codex binary is available locally."""
        command = self.codex_command
        if os.sep in command:
            resolved = Path(command).expanduser()
            if not resolved.is_file():
                raise ProviderLaunchError(f"Configured Codex binary `{resolved}` does not exist.")
            return
        if shutil.which(command) is None:
            raise ProviderLaunchError(f"Codex binary `{command}` is not available on PATH.")



    def build_launch_spec(
        self,
        session: RuntimeSessionRecord,
        *,
        secret_env: dict[str, str] | None = None,
        credential_binding_id: str | None = None,
        resolved_secret_refs: list[str] | None = None,
        model_id: str | None = None,
        model_reasoning_effort: str | None = None,
    ) -> RuntimeBackendLaunchSpec:
        """Build one runtime launch spec for the local Codex backend."""
        self.validate_backend()
        selected_model, selected_reasoning = self.validate_model_settings(model_id, model_reasoning_effort)
        workdir = Path(session.workdir)
        workspace_root = Path(session.workspace_root)
        runtime_root = Path(session.runtime_root)
        host_command = self._runtime_command(self.codex_command)
        runtime_bin = self._prepare_runtime_bin(session, host_command=host_command)
        runtime_home = self._runtime_home(session)
        env = self._build_subprocess_env(
            workdir=workdir,
            workspace_root=workspace_root,
            runtime_root=runtime_root,
            runtime_home=runtime_home,
            runtime_bin=runtime_bin,
            session=session,
            execution_mode=session.effective_mode,
            secret_env=secret_env,
        )
        runtime_home = self._prepare_runtime_home(
            session,
            runtime_bin=runtime_bin,
            shell_path=env.get("PATH"),
            model_id=selected_model,
            model_reasoning_effort=selected_reasoning,
        )
        return RuntimeBackendLaunchSpec(
            provider_id="codex",
            command=self._build_command(
                workspace_root=workspace_root,
                runtime_root=runtime_root,
                runtime_bin=runtime_bin,
                execution_mode=session.effective_mode,
                host_command=host_command,
            ),
            env_overrides=env,
            credential_binding_id=credential_binding_id,
            resolved_secret_refs=list(resolved_secret_refs or []),
            working_directory=str(workdir),
            execution_mode=session.effective_mode,
            readable_roots=self._readable_roots(
                workspace_root=workspace_root,
                execution_mode=session.effective_mode,
            ),
            writable_roots=self._writable_roots(
                workspace_root=workspace_root,
                execution_mode=session.effective_mode,
            ),
        )



    def prepare_runtime_skills(
        self,
        session: RuntimeSessionRecord,
        skills: list["SkillDefinition"],
    ) -> list["SkillMaterialization"]:
        """Install skills into the Codex runtime home using provider-specific layout rules."""
        from core.skills.models import SkillMaterialization

        runtime_home = self._runtime_home(session)
        skills_root = runtime_home / "skills"
        skills_root.mkdir(parents=True, exist_ok=True)
        materializations: list[SkillMaterialization] = []
        for skill in skills:
            source_root = Path(skill.source_root).resolve()
            target_root = skills_root.joinpath(*skill.skill_id.split("."))
            if target_root.exists() or target_root.is_symlink():
                if target_root.is_symlink() or target_root.is_file():
                    target_root.unlink()
                else:
                    shutil.rmtree(target_root)
            target_root.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source_root, target_root, dirs_exist_ok=True)
            materializations.append(
                SkillMaterialization(
                    provider_id="codex",
                    skill_id=skill.skill_id,
                    source_root=str(source_root),
                    target_root=str(target_root),
                    strategy="copy",
                )
            )
        return materializations



    def execute_turn(
        self,
        *,
        session: RuntimeSessionRecord,
        launch_spec: RuntimeBackendLaunchSpec,
        input_text: str,
        event_sink: RuntimeExecutionEventSink | None = None,
        timeout_seconds: int | None = None,
        on_provider_thread_id: Callable[[str], None] | None = None,
        on_provider_turn_start_sent: Callable[[dict[str, object]], None] | None = None,
        on_provider_accepted: Callable[[dict[str, object]], None] | None = None,
        command_runner=subprocess.Popen,
    ) -> "RuntimeExecutionResult":
        """Execute one turn through the Codex app-server runtime."""
        from core.providers.codex_app_server import execute_codex_app_server_turn
        from core.runtime.execution import RuntimeExecutionResult

        result = execute_codex_app_server_turn(
            session=session,
            launch_spec=launch_spec,
            input_text=input_text,
            event_sink=event_sink,
            timeout_seconds=timeout_seconds,
            on_provider_thread_id=on_provider_thread_id,
            on_provider_turn_start_sent=on_provider_turn_start_sent,
            on_provider_accepted=on_provider_accepted,
            command_runner=command_runner,
        )
        return RuntimeExecutionResult(output_text=result.output_text, exit_code=result.exit_code)



    def close_runtime(self, session_id: str) -> int:
        """Close any persistent Codex app-server runtime for one session."""
        from core.providers.codex_app_server import close_codex_app_server_runtime

        return close_codex_app_server_runtime(session_id)



    def interrupt_turn(self, session_id: str) -> bool:
        """Interrupt the active Codex app-server turn for one session."""
        from core.providers.codex_app_server import interrupt_codex_app_server_turn

        return interrupt_codex_app_server_turn(session_id)
