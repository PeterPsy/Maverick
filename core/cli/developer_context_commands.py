"""Core CLI commands for canonical developer context."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.cli.core_command_helpers import WORKSPACE_SAFE, core_cli_command
from core.cli.models import CliCommandDefinition, CliInvocationContext
from core.developer_context.service import list_documents, read_document


def developer_context_command_specs(*, start_path: Path | None = None) -> list[tuple[CliCommandDefinition, Any]]:
    """Build read-only CLI commands for canonical developer context."""

    def _list_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        return {"command_id": "developer-context.list", "items": list_documents()}

    def _read_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        return {"command_id": "developer-context.read", **read_document(doc_id=str(arguments.get("doc_id") or ""), start_path=start_path)}

    command_specs = [
        ("developer-context.list", ["developer-context", "list"], "List canonical developer context documents available through the core.", _list_handler),
        ("developer-context.read", ["developer-context", "read"], "Read one canonical developer context document by doc_id.", _read_handler),
    ]
    return [
        (
            core_cli_command(
                command_id=command_id,
                path_segments=path_segments,
                description=description,
                owner_id="developer-context",
                invocation_policy=WORKSPACE_SAFE,
                agentic_result_data_class=(
                    "public"
                    if command_id == "developer-context.list"
                    else None
                ),
            ),
            handler,
        )
        for command_id, path_segments, description, handler in command_specs
    ]
