"""Codex runtime backend adapter."""

from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path
import shutil
from typing import TYPE_CHECKING

from core.providers.models import ProviderCapabilitySet, ProviderDefinition, ProviderModelOption, ProviderReasoningOption
from core.providers.provider_codex_hooks import CODEX_POST_TOOL_USE_HOOK_NAME, write_codex_post_tool_use_hook
from core.providers.provider_codex_wrappers import _write_workspace_maverick_wrapper
from core.runtime.runtime_session import RuntimeSessionRecord

if TYPE_CHECKING:
    from core.runtime.execution import RuntimeExecutionResult
    from core.skills.models import SkillDefinition, SkillMaterialization

CODEX_RUNTIME_HOME_FILES = ("auth.json", "version.json", ".personality_migration", "installation_id")
CODEX_DISABLED_RUNTIME_FEATURES = ("apps", "plugins")
CODEX_SYSTEM_SKILLS_ROOT = ".system"
CODEX_DEFAULT_MODEL = "gpt-5.6-sol"
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
            supports_same_turn_input=True,
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


def remove_codex_system_skills(runtime_home: Path) -> None:
    """Remove Codex-generated system skills from a Maverick-managed runtime home."""
    system_root = Path(runtime_home) / "skills" / CODEX_SYSTEM_SKILLS_ROOT
    if system_root.is_symlink() or system_root.is_file():
        system_root.unlink(missing_ok=True)
        return
    if system_root.is_dir():
        shutil.rmtree(system_root, ignore_errors=True)




class CodexRuntimeHomeMixin:
    def _runtime_home(self, session: RuntimeSessionRecord) -> Path:
        return Path(session.runtime_root) / "codex-home"



    def _prepare_runtime_home(
        self,
        session: RuntimeSessionRecord,
        *,
        runtime_bin: Path | None = None,
        shell_path: str | None = None,
        model_id: str | None = None,
        model_reasoning_effort: str | None = None,
    ) -> Path:
        runtime_home = self._runtime_home(session)
        runtime_home.mkdir(parents=True, exist_ok=True)
        source_home = self._source_codex_home()
        if self._same_path(runtime_home, source_home):
            return runtime_home
        self._remove_disabled_runtime_material(runtime_home)
        for filename in CODEX_RUNTIME_HOME_FILES:
            self._copy_file_if_present(source_home / filename, runtime_home / filename)
        self._write_runtime_config(
            source_home / "config.toml",
            runtime_home / "config.toml",
            workspace_root=Path(session.workspace_root),
            runtime_root=Path(session.runtime_root),
            runtime_bin=runtime_bin or Path(session.runtime_root) / "bin",
            shell_path=shell_path,
            execution_mode=session.effective_mode,
            model_id=model_id,
            model_reasoning_effort=model_reasoning_effort,
        )
        self._link_or_copy_if_present(source_home / "rules", runtime_home / "rules")
        self._remove_disabled_runtime_material(runtime_home)
        remove_codex_system_skills(runtime_home)
        return runtime_home



    def _prepare_runtime_bin(self, session: RuntimeSessionRecord, *, host_command: str | None = None) -> Path:
        runtime_bin = Path(session.runtime_root) / "bin"
        runtime_bin.mkdir(parents=True, exist_ok=True)
        _write_workspace_maverick_wrapper(runtime_bin / "maverick")
        write_codex_post_tool_use_hook(runtime_bin / CODEX_POST_TOOL_USE_HOOK_NAME)
        sandbox_launcher = runtime_bin / "workspace_sandbox.py"
        shutil.copy2(Path(__file__).resolve().parents[1] / "runtime" / "workspace_sandbox.py", sandbox_launcher)
        sandbox_launcher.chmod(0o755)
        host_command_path = Path(host_command or self._runtime_command(self.codex_command))
        self._install_runtime_tool_if_present(
            runtime_bin=runtime_bin,
            source=self._vendored_codex_tool_binary(host_command_path, "rg"),
            tool_name="rg",
        )
        return runtime_bin



    def _install_runtime_tool_if_present(self, *, runtime_bin: Path, source: Path | None, tool_name: str) -> None:
        destination = runtime_bin / tool_name
        self._reset_path(destination)
        if source is None or not source.is_file():
            return
        shutil.copy2(source, destination)
        destination.chmod(destination.stat().st_mode | 0o111)



    def _source_codex_home(self) -> Path:
        configured = str(os.environ.get("MAVERICK_CODEX_HOME") or os.environ.get("CODEX_HOME") or "").strip()
        if configured:
            return Path(configured).expanduser()
        return Path.home() / ".codex"



    def _same_path(self, left: Path, right: Path) -> bool:
        try:
            return left.resolve(strict=False) == right.resolve(strict=False)
        except OSError:
            return False



    def _copy_file_if_present(self, source: Path, destination: Path) -> None:
        try:
            if not source.is_file():
                return
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        except OSError:
            return



    def _write_runtime_config(
        self,
        source: Path,
        destination: Path,
        *,
        workspace_root: Path,
        runtime_root: Path,
        runtime_bin: Path,
        execution_mode: str,
        shell_path: str | None = None,
        model_id: str | None = None,
        model_reasoning_effort: str | None = None,
    ) -> None:
        raw_lines = self._read_runtime_config_lines(source)
        sanitized_lines: list[str] = []
        skipping_disabled_section = False
        current_section: str | None = None
        for line in raw_lines:
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                current_section = stripped
                skipping_disabled_section = self._is_disabled_runtime_config_section(
                    stripped,
                    workspace_root=workspace_root,
                    execution_mode=execution_mode,
                )
                if skipping_disabled_section:
                    continue
            if skipping_disabled_section:
                continue
            if self._is_managed_model_config_key(stripped, current_section=current_section):
                continue
            sanitized_lines.append(line)
        selected_model = str(model_id or "").strip() or self.default_model_id()
        selected_reasoning = str(model_reasoning_effort or "").strip() or CODEX_DEFAULT_REASONING_EFFORT
        output_lines = [f'model = "{selected_model}"']
        if selected_reasoning:
            output_lines.append(f'model_reasoning_effort = "{selected_reasoning}"')
        output_lines.extend(self._managed_top_level_runtime_config_lines())
        if sanitized_lines:
            output_lines.append("")
            output_lines.extend(sanitized_lines)
        if output_lines and output_lines[-1].strip():
            output_lines.append("")
        output_lines.extend(
            self._managed_shell_environment_policy_lines(
                workspace_root=workspace_root,
                runtime_root=runtime_root,
                runtime_bin=runtime_bin,
                shell_path=shell_path,
                execution_mode=execution_mode,
            )
        )
        if output_lines and output_lines[-1].strip():
            output_lines.append("")
        output_lines.extend(self._managed_codex_hook_lines(runtime_bin=runtime_bin, config_path=destination))
        if output_lines and output_lines[-1].strip():
            output_lines.append("")
        output_lines.extend(self._managed_runtime_feature_lines())
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("\n".join(output_lines).strip() + "\n", encoding="utf-8")
