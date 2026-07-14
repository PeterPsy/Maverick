"""Codex runtime backend adapter."""

from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path
import shutil
from typing import TYPE_CHECKING

from core.providers.models import ProviderCapabilitySet, ProviderDefinition, ProviderModelOption, ProviderReasoningOption
from core.providers.provider_codex_command_paths import CodexCommandPathMixin
from core.providers.provider_codex_commands import CodexCommandMixin
from core.providers.provider_codex_config import CodexRuntimeConfigMixin
from core.providers.provider_codex_launch import CodexLaunchMixin
from core.providers.provider_codex_models import CodexModelMixin
from core.providers.provider_codex_runtime_home import CodexRuntimeHomeMixin
from core.providers.provider_codex_wrappers import refresh_workspace_maverick_wrappers

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

__all__ = [
    "CodexProviderAdapter",
    "build_codex_definition",
    "refresh_workspace_maverick_wrappers",
    "remove_codex_system_skills",
]


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
        provider_role="runtime_engine",
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
            input_modalities=["text"],
            output_modalities=["text", "events"],
            supports_streaming_output=True,
            supports_tool_calling=True,
            latency_class="interactive_runtime",
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



class CodexProviderAdapter(
    CodexModelMixin,
    CodexLaunchMixin,
    CodexCommandMixin,
    CodexRuntimeHomeMixin,
    CodexRuntimeConfigMixin,
    CodexCommandPathMixin,
):
    def __init__(
        self,
        *,
        codex_command: str | None = None,
        server_args: list[str] | None = None,
    ) -> None:
        self.codex_command = str(codex_command or os.environ.get("MAVERICK_CODEX_COMMAND") or "").strip() or "codex"
        self.server_args = list(server_args or ["app-server", "--listen", "stdio://"])


    def provider_definition(self) -> ProviderDefinition:
        """Return the canonical definition exposed by this adapter."""
        return build_codex_definition()


def remove_codex_system_skills(runtime_home: Path) -> None:
    """Remove Codex-generated system skills from a Maverick-managed runtime home."""
    system_root = Path(runtime_home) / "skills" / CODEX_SYSTEM_SKILLS_ROOT
    if system_root.is_symlink() or system_root.is_file():
        system_root.unlink(missing_ok=True)
        return
    if system_root.is_dir():
        shutil.rmtree(system_root, ignore_errors=True)
