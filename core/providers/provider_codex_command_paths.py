"""Codex runtime backend adapter."""

from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path
import shlex
import shutil
from typing import TYPE_CHECKING

from core.providers.models import ProviderCapabilitySet, ProviderDefinition, ProviderModelOption, ProviderReasoningOption

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




class CodexCommandPathMixin:
    def _readable_roots(self, *, workspace_root: Path, execution_mode: str) -> list[str]:
        if execution_mode == "full-access":
            return ["/"]
        return [str(workspace_root)]



    def _writable_roots(self, *, workspace_root: Path, execution_mode: str) -> list[str]:
        if execution_mode == "full-access":
            return ["/"]
        return [str(workspace_root)]



    def _dependency_root_args(self, command: str) -> list[str]:
        roots = self._command_dependency_roots(command)
        args: list[str] = []
        for root in roots:
            args.extend(["--dependency-root", str(root)])
        return args



    def _runtime_command(self, command: str) -> str:
        command_path = self._command_path(command)
        if command_path is None:
            return command
        resolved = command_path.resolve(strict=False)
        launch_path = self._codex_launch_path(command_path)
        standalone = self._standalone_codex_binary(launch_path)
        if standalone is not None:
            return str(standalone)
        if launch_path != resolved:
            return str(launch_path)
        return str(command_path)



    def _command_dependency_roots(self, command: str) -> list[Path]:
        command_path = self._command_path(command)
        if command_path is None:
            return []
        resolved = self._codex_launch_path(command_path)
        if self._is_standalone_codex_binary(resolved):
            return [resolved.parent]
        standalone = self._standalone_codex_binary(resolved)
        if standalone is not None:
            return [standalone.parent]
        if any(resolved.is_relative_to(Path(root)) for root in ("/usr", "/bin", "/lib", "/lib64")):
            return []
        return [resolved.parent]



    def _command_path(self, command: str) -> Path | None:
        path_entries = [entry for entry in str(os.environ.get("PATH") or "").split(os.pathsep) if entry]
        resolved_value = command if os.sep in command else shutil.which(command, path=os.pathsep.join(path_entries))
        if not resolved_value:
            return None
        return Path(resolved_value).expanduser()



    def _codex_launch_path(self, command_path: Path) -> Path:
        resolved = command_path.resolve(strict=False)
        wrapper_target = self._codex_wrapper_target(resolved)
        return wrapper_target or resolved



    def _codex_wrapper_target(self, resolved: Path) -> Path | None:
        if resolved.name == "codex.js" or self._is_standalone_codex_binary(resolved):
            return None
        try:
            if not resolved.is_file():
                return None
            with resolved.open("rb") as handle:
                text = handle.read(8192).decode("utf-8", errors="ignore")
        except OSError:
            return None
        if "CODEX_REAL=" not in text:
            return None
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped.startswith("CODEX_REAL="):
                continue
            raw_value = stripped.split("=", 1)[1].strip()
            try:
                parts = shlex.split(raw_value, posix=True)
            except ValueError:
                parts = []
            value = parts[0] if parts else raw_value.strip("\"'")
            if not value:
                continue
            target = Path(value).expanduser()
            if not target.is_absolute():
                target = resolved.parent / target
            target = target.resolve(strict=False)
            if self._is_codex_node_entrypoint(target):
                return target
        return None



    def _is_codex_node_entrypoint(self, resolved: Path) -> bool:
        return (
            resolved.name == "codex.js"
            and resolved.parent.name == "bin"
            and resolved.parent.parent.name == "codex"
            and resolved.is_file()
        )



    def _standalone_codex_binary(self, resolved: Path) -> Path | None:
        if self._is_standalone_codex_binary(resolved):
            return resolved
        package_root = resolved.parent.parent if resolved.name == "codex.js" and resolved.parent.name == "bin" else None
        if package_root is None or package_root.name != "codex":
            return None
        vendor_root = package_root / "node_modules" / "@openai"
        if not vendor_root.exists():
            return None
        candidates = sorted(vendor_root.glob("codex-linux-*/vendor/*/codex/codex"))
        for candidate in candidates:
            if candidate.is_file():
                return candidate.resolve(strict=False)
        return None



    def _vendored_codex_tool_binary(self, standalone_codex: Path, tool_name: str) -> Path | None:
        if not self._is_standalone_codex_binary(standalone_codex):
            return None
        candidate = standalone_codex.parent.parent / "path" / tool_name
        if candidate.is_file():
            return candidate.resolve(strict=False)
        return None



    def _is_standalone_codex_binary(self, resolved: Path) -> bool:
        return resolved.name == "codex" and resolved.parent.name == "codex" and "vendor" in resolved.parts
