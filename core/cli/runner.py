"""Execution runner for platform-managed CLI commands."""

from __future__ import annotations

from typing import Any

from core.cli.command_registry import CliCommandRegistry
from core.cli.errors import CliInvocationNotAllowedError
from core.cli.models import CliInvocationContext, CliInvocationPolicy


def _enforce_invocation_policy(policy: CliInvocationPolicy, context: CliInvocationContext) -> None:
    if policy.operator_only and context.caller_kind != "operator":
        raise CliInvocationNotAllowedError("This CLI command is operator-only.")
    if context.caller_kind == "sandbox_agent" and not policy.sandbox_agent_allowed:
        raise CliInvocationNotAllowedError("Sandboxed agents may not invoke this CLI command.")
    if policy.requires_workspace_context and not context.workspace_id:
        raise CliInvocationNotAllowedError("This CLI command requires a trusted workspace context.")
    if policy.requires_full_access and context.effective_mode != "full-access":
        raise CliInvocationNotAllowedError("This CLI command requires full-access execution mode.")


class CliRunner:
    """Run registered CLI commands after policy enforcement."""

    def __init__(self, registry: CliCommandRegistry) -> None:
        self.registry = registry

    def run_command(
        self,
        *,
        command_id: str,
        arguments: dict[str, Any] | None,
        context: CliInvocationContext,
    ) -> dict[str, Any]:
        """Run one registered command under the provided trusted context."""
        definition = self.registry.get_command(command_id)
        _enforce_invocation_policy(definition.invocation_policy, context)
        handler = self.registry.get_handler(command_id)
        return handler(arguments or {}, context)
