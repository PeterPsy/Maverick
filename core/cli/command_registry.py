"""Registry for CLI command definitions and handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core.cli.errors import CliCommandNotFoundError
from core.cli.models import CliCommandDefinition, CliInvocationContext


CliCommandHandler = Callable[[dict[str, Any], CliInvocationContext], dict[str, Any]]


class CliCommandRegistry:
    """Collect CLI command metadata separately from invocation policy and transport."""

    def __init__(self) -> None:
        self._definitions: dict[str, CliCommandDefinition] = {}
        self._handlers: dict[str, CliCommandHandler] = {}

    def register_command(self, definition: CliCommandDefinition, handler: CliCommandHandler) -> CliCommandDefinition:
        """Register one command definition and its handler."""
        self._definitions[definition.command_id] = definition
        self._handlers[definition.command_id] = handler
        return definition

    def list_commands(self) -> list[CliCommandDefinition]:
        """Return all registered commands in deterministic order."""
        return [self._definitions[command_id] for command_id in sorted(self._definitions)]

    def get_command(self, command_id: str) -> CliCommandDefinition:
        """Return one command definition by id."""
        if command_id not in self._definitions:
            raise CliCommandNotFoundError(f"CLI command `{command_id}` is not registered.")
        return self._definitions[command_id]

    def get_handler(self, command_id: str) -> CliCommandHandler:
        """Return the handler for one registered command."""
        if command_id not in self._handlers:
            raise CliCommandNotFoundError(f"CLI command `{command_id}` is not registered.")
        return self._handlers[command_id]
