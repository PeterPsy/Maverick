"""Trusted catalog authorization for native CLI model invocations."""

from __future__ import annotations

from core.model_access.models import ModelAccessCatalog


DIAGNOSTIC_CODEX_INVOCATIONS = {
    ("--version",),
    ("debug", "models"),
    ("login", "status"),
}


def authorize_cli_invocation(
    catalog: ModelAccessCatalog,
    *,
    provider_id: str,
    argv: tuple[str, ...],
) -> str | None:
    """Require an available catalog model for every non-diagnostic command."""
    if provider_id == "codex" and argv in DIAGNOSTIC_CODEX_INVOCATIONS:
        return None
    positions = [index for index, argument in enumerate(argv) if argument == "--model"]
    if len(positions) != 1 or positions[0] + 1 >= len(argv):
        raise ValueError("CLI model execution must select exactly one model")
    selected_model = argv[positions[0] + 1]
    matches = [
        model
        for model in catalog.cli_models
        if model.available
        and model.provider_id == provider_id
        and model.transport == "cli"
        and model.model_id == selected_model
    ]
    if len(matches) != 1:
        raise PermissionError("CLI model is outside the scoped catalog")
    return selected_model


__all__ = ["DIAGNOSTIC_CODEX_INVOCATIONS", "authorize_cli_invocation"]
