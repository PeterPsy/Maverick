"""Shared helpers for the Maverick SDK CLI wrapper."""

from __future__ import annotations

from core.app_sdk.cli_contexts import _cli_commands, _cli_context, _mcp_context, _mcp_tools
from core.app_sdk.cli_descriptors import (
    _app_scoped_id,
    _command_detail,
    _command_summary,
    _require_cli_command,
    _require_mcp_tool,
    _run_target_and_arguments,
    _single_id,
    _tool_detail,
    _tool_summary,
)
from core.app_sdk.cli_surface_runners import _run_app_cli, _run_app_mcp, _run_core_cli, _run_core_mcp
from core.app_sdk.cli_syntax import (
    _die,
    _extract_repository_root,
    _help_text,
    _split_wrapper_options,
    _workspace_id,
    _wants_help,
)

__all__ = [
    "_app_scoped_id",
    "_cli_commands",
    "_cli_context",
    "_command_detail",
    "_command_summary",
    "_die",
    "_extract_repository_root",
    "_help_text",
    "_mcp_context",
    "_mcp_tools",
    "_require_cli_command",
    "_require_mcp_tool",
    "_run_app_cli",
    "_run_app_mcp",
    "_run_core_cli",
    "_run_core_mcp",
    "_run_target_and_arguments",
    "_single_id",
    "_split_wrapper_options",
    "_tool_detail",
    "_tool_summary",
    "_wants_help",
    "_workspace_id",
]
