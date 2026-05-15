"""Codex runtime backend adapter."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
import shutil
from typing import TYPE_CHECKING

from core.providers.models import ProviderCapabilitySet, ProviderDefinition, ProviderModelOption, ProviderReasoningOption

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




class CodexRuntimeConfigMixin:
    def _read_runtime_config_lines(self, source: Path) -> list[str]:
        try:
            return source.read_text(encoding="utf-8").splitlines() if source.is_file() else []
        except OSError:
            return []



    def _is_managed_model_config_key(self, stripped: str, *, current_section: str | None) -> bool:
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            return False
        key = stripped.split("=", 1)[0].strip()
        if current_section is None:
            return key in CODEX_MANAGED_TOP_LEVEL_CONFIG_KEYS
        if current_section.startswith("[profiles.") and current_section.endswith("]"):
            return key in CODEX_MANAGED_TOP_LEVEL_CONFIG_KEYS
        return False



    def _is_disabled_runtime_config_section(self, section: str, *, workspace_root: Path, execution_mode: str) -> bool:
        if self._is_managed_shell_environment_section(section):
            return True
        if section in {"[mcp_servers]", "[plugins]", "[features]"}:
            return True
        if section.startswith(("[mcp_servers.", "[plugins.", "[features.")):
            return True
        return self._is_sandbox_project_section_outside_workspace(
            section,
            workspace_root=workspace_root,
            execution_mode=execution_mode,
        )



    def _is_sandbox_project_section_outside_workspace(self, section: str, *, workspace_root: Path, execution_mode: str) -> bool:
        if execution_mode != "sandbox":
            return False
        prefix = "[projects."
        if not section.startswith(prefix) or not section.endswith("]"):
            return False
        raw_project = section[len(prefix) : -1].strip()
        if len(raw_project) >= 2 and raw_project[0] == raw_project[-1] and raw_project[0] in {'"', "'"}:
            raw_project = raw_project[1:-1]
        if not raw_project:
            return True
        workspace = workspace_root.expanduser().resolve(strict=False)
        project = Path(raw_project).expanduser().resolve(strict=False)
        return project != workspace and not project.is_relative_to(workspace)



    def _is_managed_shell_environment_section(self, section: str) -> bool:
        table = section.strip().lstrip("[").rstrip("]").strip()
        return table == "shell_environment_policy" or table.startswith("shell_environment_policy.")



    def _managed_shell_environment_policy_lines(
        self,
        *,
        workspace_root: Path,
        runtime_root: Path,
        runtime_bin: Path,
        execution_mode: str,
    ) -> list[str]:
        path_value = os.pathsep.join(
            self._dedupe_path_entries(
                [
                    str(runtime_bin),
                    *str(os.environ.get("PATH") or "").split(os.pathsep),
                ]
            )
        )
        api_base = str(os.environ.get("MAVERICK_API_BASE") or "http://127.0.0.1:8014").rstrip("/")
        return [
            "[shell_environment_policy.set]",
            f"PATH = {_toml_string(path_value)}",
            f"MAVERICK_RUNTIME_BIN = {_toml_string(str(runtime_bin))}",
            f"MAVERICK_RUNTIME_ROOT = {_toml_string(str(runtime_root))}",
            f"MAVERICK_WORKSPACE_ROOT = {_toml_string(str(workspace_root))}",
            f"MAVERICK_EFFECTIVE_MODE = {_toml_string(execution_mode)}",
            f"MAVERICK_API_BASE = {_toml_string(api_base)}",
        ]



    def _dedupe_path_entries(self, entries: list[str]) -> list[str]:
        unique: list[str] = []
        seen: set[str] = set()
        for entry in entries:
            normalized = str(entry or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            unique.append(normalized)
        return unique



    def _managed_runtime_feature_lines(self) -> list[str]:
        lines = ["[features]"]
        for name, enabled in CODEX_MANAGED_RUNTIME_FEATURES.items():
            lines.append(f"{name} = {str(enabled).lower()}")
        return lines



    def _remove_disabled_runtime_material(self, runtime_home: Path) -> None:
        for path in (
            runtime_home / "plugins",
            runtime_home / "skills" / CODEX_SYSTEM_SKILLS_ROOT,
            runtime_home / "cache" / "codex_apps_tools",
            runtime_home / ".tmp" / "plugins",
            runtime_home / ".tmp" / "plugins.sha",
            runtime_home / ".tmp" / "app-server-remote-plugin-sync-v1",
        ):
            self._reset_path(path)



    def _link_or_copy_if_present(self, source: Path, destination: Path) -> None:
        if not source.exists():
            return
        self._reset_path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(source, destination)



    def _reset_path(self, path: Path) -> None:
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
            return
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)



    def _launcher_pythonpath(self, existing: str | None) -> str:
        repo_root = Path(__file__).resolve().parents[2]
        entries = [str(repo_root)]
        entries.extend(entry for entry in str(existing or "").split(os.pathsep) if entry)
        unique: list[str] = []
        seen: set[str] = set()
        for entry in entries:
            if entry in seen:
                continue
            seen.add(entry)
            unique.append(entry)
        return os.pathsep.join(unique)


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)
