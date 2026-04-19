"""Public CLI service facade."""

from core.cli.registry_builder import build_core_cli_registry, list_core_cli_commands, run_core_cli_command

__all__ = ["build_core_cli_registry", "list_core_cli_commands", "run_core_cli_command"]
