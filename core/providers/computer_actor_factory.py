"""Executable provider boundary for the internal UI decision operator."""

from core.providers.codex_computer_actor import CodexComputerActor
from core.providers.errors import ProviderSelectionError
from core.providers.computer_actor_settings import validate_computer_actor_selection


def create_computer_actor(session, binding, *, selection):
    validate_computer_actor_selection(selection)
    if selection.provider_id == "codex":
        return CodexComputerActor(session, binding, selection=selection)
    raise ProviderSelectionError("computer_use_provider_unavailable")
