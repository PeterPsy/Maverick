"""Workspace-scoped catalog discovery for the naked-model bridge."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat

from core.model_access.models import ModelAccessCatalog, ModelAccessModel, ModelAccessScope
from core.providers.provider_credentials import resolve_provider_binding
from core.secrets.secret_resolution import parse_secret_ref


OPENAI_COMPATIBLE_PROVIDERS = {"openrouter"}


def build_model_access_catalog(state, scope: ModelAccessScope) -> ModelAccessCatalog:
    """Return configured API/CLI models without consulting runtime or memory state."""
    api_models: list[ModelAccessModel] = []
    cli_models: list[ModelAccessModel] = []
    cli_defaults: dict[str, str] = {}
    definitions = sorted(
        state.provider_store.list_provider_definitions(),
        key=lambda item: item.provider_id,
    )
    for definition in definitions:
        if definition.status != "active":
            continue
        if scope.api and definition.provider_id in OPENAI_COMPATIBLE_PROVIDERS:
            available = _provider_credential_available(state, scope, definition.provider_id)
            for option in definition.model_options:
                api_models.append(
                    ModelAccessModel(
                        model_id=option.model_id,
                        label=option.label,
                        provider_id=definition.provider_id,
                        transport="api",
                        available=available,
                        capabilities=_capabilities(definition),
                    )
                )
        if definition.provider_id in scope.cli:
            available = (
                definition.provider_id == "codex"
                and resolve_codex_executable() is not None
                and (resolve_codex_source_home() / "auth.json").is_file()
            )
            for option in definition.model_options:
                cli_models.append(
                    ModelAccessModel(
                        model_id=option.model_id,
                        label=option.label,
                        provider_id=definition.provider_id,
                        transport="cli",
                        available=available,
                        capabilities=_capabilities(definition),
                    )
                )
            selection = state.provider_store.get_provider_selection(scope.workspace_id)
            if selection is not None and selection.provider_id == definition.provider_id and selection.model_id:
                cli_defaults[definition.provider_id] = selection.model_id
            elif definition.default_model_family:
                cli_defaults[definition.provider_id] = definition.default_model_family
    return ModelAccessCatalog(
        api_models=tuple(api_models),
        cli_models=tuple(cli_models),
        cli_defaults=cli_defaults,
    )


def resolve_codex_executable() -> Path | None:
    """Resolve a non-writable standalone Codex binary, never an operator shell shim."""
    configured = os.environ.get("MAVERICK_MODEL_ACCESS_CODEX_BIN", "").strip()
    candidates: list[Path] = [Path(configured).expanduser()] if configured else []
    launch = shutil.which("codex")
    if launch:
        resolved = Path(launch).resolve(strict=False)
        candidates.extend(
            sorted(
                resolved.parent.parent.glob(
                    "lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-*/vendor/*/bin/codex"
                )
            )
        )
    candidates.extend(
        sorted(
            Path("/usr/local/lib/node_modules/@openai/codex/node_modules/@openai").glob(
                "codex-linux-*/vendor/*/bin/codex"
            )
        )
    )
    for candidate in candidates:
        try:
            path = candidate.resolve(strict=True)
            metadata = path.stat()
        except OSError:
            continue
        if (
            stat.S_ISREG(metadata.st_mode)
            and metadata.st_mode & 0o111
            and not metadata.st_mode & 0o022
        ):
            return path
    return None


def resolve_codex_source_home() -> Path:
    """Return the operator-owned Codex auth home, excluding runtime-session homes."""
    configured = os.environ.get("MAVERICK_MODEL_ACCESS_CODEX_HOME", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".codex"


def _provider_credential_available(state, scope: ModelAccessScope, provider_id: str) -> bool:
    try:
        binding = resolve_provider_binding(
            state.provider_store,
            provider_id=provider_id,
            workspace_id=scope.workspace_id,
        )
        if binding is None:
            return False
        parsed = parse_secret_ref(binding.secret_ref)
        secret = (
            state.secret_store.get_secret(parsed.value)
            if parsed.kind == "secret_id"
            else state.secret_store.get_secret_by_alias(parsed.value)
        )
    except Exception:
        return False
    return secret.status == "active"


def _capabilities(definition) -> dict[str, object]:
    capabilities = definition.capabilities
    return {
        "streaming": bool(capabilities.supports_streaming),
        "tools": bool(capabilities.supports_tools),
        "filesystem": bool(capabilities.supports_filesystem_access),
        "input_modalities": list(capabilities.input_modalities),
        "output_modalities": list(capabilities.output_modalities),
        "cancellation": True,
    }
