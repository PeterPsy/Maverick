"""MCP-domain errors."""

from __future__ import annotations


class McpError(Exception):
    """Base error for the MCP domain."""


class McpInvocationNotAllowedError(McpError):
    """Raised when policy denies one MCP invocation."""
