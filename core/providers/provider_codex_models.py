"""Codex runtime backend adapter."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import os
import shutil
import subprocess
from time import monotonic
from typing import TYPE_CHECKING

from core.providers.errors import ProviderSelectionError
from core.providers.models import ProviderCapabilitySet, ProviderDefinition, ProviderModelOption, ProviderReasoningOption

if TYPE_CHECKING:
    from core.runtime.execution import RuntimeExecutionResult
    from core.skills.models import SkillDefinition, SkillMaterialization

CODEX_RUNTIME_HOME_FILES = ("auth.json", "version.json", ".personality_migration", "installation_id")
CODEX_DISABLED_RUNTIME_FEATURES = ("apps", "plugins")
CODEX_SYSTEM_SKILLS_ROOT = ".system"
CODEX_DEFAULT_MODEL = "gpt-5.6-sol"
CODEX_DEFAULT_REASONING_EFFORT = "high"
CODEX_MODEL_CATALOG_TTL_SECONDS = 300
CODEX_MANAGED_TOP_LEVEL_CONFIG_KEYS = {"model", "model_reasoning_effort"}
CODEX_MANAGED_RUNTIME_FEATURES = {
    "apps": False,
    "plugins": False,
    "skill_mcp_dependency_install": False,
}
_MODEL_OPTIONS_CACHE: dict[str, tuple[float, list[ProviderModelOption]]] = {}


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



class CodexModelMixin:
    def model_options(self, *, refresh: bool = False) -> list[ProviderModelOption]:
        """Return model options currently reported by the configured Codex binary."""
        command = self._runtime_command(self.codex_command)
        cached = None if refresh else self._cached_model_options(command)
        if cached is not None:
            return cached
        options, cacheable = self._discover_model_options(command=command)
        if cacheable:
            self._store_model_options_cache(command, options)
        elif refresh:
            _MODEL_OPTIONS_CACHE.pop(command, None)
        return list(options)


    def _cached_model_options(self, command: str) -> list[ProviderModelOption] | None:
        cached = _MODEL_OPTIONS_CACHE.get(command)
        if cached is None:
            return None
        cached_at, cached_options = cached
        if monotonic() - cached_at > CODEX_MODEL_CATALOG_TTL_SECONDS:
            return None
        return list(cached_options)


    def _store_model_options_cache(self, command: str, options: list[ProviderModelOption]) -> None:
        _MODEL_OPTIONS_CACHE[command] = (monotonic(), list(options))


    def _discover_model_options(self, *, command: str) -> tuple[list[ProviderModelOption], bool]:
        try:
            result = subprocess.run(
                [command, "debug", "models"],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            payload = json.loads(result.stdout)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            return _fallback_model_options(), False
        models = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(models, list):
            return _fallback_model_options(), False
        options = [
            option
            for item in models
            if isinstance(item, dict)
            for option in [self._model_option_from_catalog_item(item)]
            if option is not None
        ]
        if not options:
            return _fallback_model_options(), False
        return options, True


    def default_model_id(self, options: list[ProviderModelOption] | None = None) -> str:
        """Return Maverick's preferred Codex model when it is available."""
        return _default_model_id(list(options or self.model_options()))


    def validate_model_settings(self, model_id: str | None, reasoning_effort: str | None) -> tuple[str, str | None]:
        """Validate and normalize a requested Codex model and reasoning effort."""
        options = self.model_options()
        selected_model = str(model_id or "").strip() or self.default_model_id(options)
        option = next((item for item in options if item.model_id == selected_model), None)
        if option is None:
            raise ProviderSelectionError(f"Codex model `{selected_model}` is not available.")
        selected_reasoning = str(reasoning_effort or "").strip() or _default_reasoning_effort(option)
        supported_reasoning = {item.effort for item in option.supported_reasoning_efforts}
        if selected_reasoning and supported_reasoning and selected_reasoning not in supported_reasoning:
            raise ProviderSelectionError(
                f"Reasoning effort `{selected_reasoning}` is not available for Codex model `{selected_model}`."
            )
        return selected_model, selected_reasoning


    def _model_option_from_catalog_item(self, item: dict) -> ProviderModelOption | None:
        if item.get("visibility") != "list":
            return None
        model_id = str(item.get("slug") or "").strip()
        if not model_id:
            return None
        reasoning_items = item.get("supported_reasoning_levels")
        reasoning_options = [
            ProviderReasoningOption(
                effort=str(reasoning.get("effort") or "").strip(),
                label=self._reasoning_label(str(reasoning.get("effort") or "").strip()),
                description=str(reasoning.get("description") or "").strip() or None,
            )
            for reasoning in reasoning_items
            if isinstance(reasoning, dict) and str(reasoning.get("effort") or "").strip()
        ] if isinstance(reasoning_items, list) else []
        return ProviderModelOption(
            model_id=model_id,
            label=str(item.get("display_name") or model_id).strip(),
            description=str(item.get("description") or "").strip() or None,
            default_reasoning_effort=str(item.get("default_reasoning_level") or "").strip() or None,
            supported_reasoning_efforts=reasoning_options,
        )


    def _reasoning_label(self, effort: str) -> str:
        return {
            "low": "Low",
            "medium": "Mid",
            "high": "High",
            "xhigh": "Extra high",
        }.get(effort, effort)
