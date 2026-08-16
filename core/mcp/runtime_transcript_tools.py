"""Read-only core MCP tools for authorized runtime transcripts."""

from __future__ import annotations

from typing import Any, Callable

from core.mcp.core_tool_helpers import WORKSPACE_SAFE, core_mcp_tool
from core.mcp.models import McpInvocationContext, McpToolDefinition
from core.runtime.errors import RuntimeTranscriptAccessError, RuntimeTranscriptValidationError
from core.runtime.store import RuntimeStore
from core.runtime.transcript_models import RuntimeTranscriptReadContext
from core.runtime.transcript_schemas import (
    THREAD_LIST_ARGUMENT_SCHEMA,
    TRANSCRIPT_MESSAGE_READ_ARGUMENT_SCHEMA,
    TRANSCRIPT_READ_ARGUMENT_SCHEMA,
)
from core.runtime.transcript_service import (
    list_runtime_transcript_threads,
    read_runtime_transcript,
    read_runtime_transcript_message,
)


def runtime_transcript_tool_specs(
    *,
    runtime_store: RuntimeStore | None = None,
    observability_store=None,
) -> list[tuple[McpToolDefinition, Any]]:
    """Build transcript MCP tools over the core runtime store."""

    def threads_list(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        return _run(
            lambda: list_runtime_transcript_threads(
                _required_store(runtime_store),
                context=_read_context(context),
                query=arguments.get("query"),
                source_app_id=arguments.get("source_app_id"),
                agent_type_id=arguments.get("agent_type_id"),
                project_id=arguments.get("project_id"),
                limit=arguments.get("limit", 20),
                cursor=arguments.get("cursor"),
                observability_store=observability_store,
                surface="mcp",
            )
        )

    def transcript_read(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        return _run(
            lambda: read_runtime_transcript(
                _required_store(runtime_store),
                context=_read_context(context),
                thread_id=str(arguments.get("thread_id") or ""),
                limit=arguments.get("limit", 30),
                before_cursor=arguments.get("before_cursor"),
                snapshot_cursor=arguments.get("snapshot_cursor"),
                profile=str(arguments.get("profile") or "messages"),
                observability_store=observability_store,
                surface="mcp",
            )
        )

    def message_read(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        return _run(
            lambda: read_runtime_transcript_message(
                _required_store(runtime_store),
                context=_read_context(context),
                thread_id=str(arguments.get("thread_id") or ""),
                message_id=str(arguments.get("message_id") or ""),
                offset=arguments.get("offset", 0),
                max_chars=arguments.get("max_chars", 12000),
                snapshot_cursor=arguments.get("snapshot_cursor"),
                observability_store=observability_store,
                surface="mcp",
            )
        )

    definitions = [
        (
            "core.runtime.threads.list",
            "List only runtime threads whose transcripts the caller may read.",
            THREAD_LIST_ARGUMENT_SCHEMA,
            threads_list,
        ),
        (
            "core.runtime.transcript.read",
            "Read a bounded page of untrusted conversation messages from complete runtime history.",
            TRANSCRIPT_READ_ARGUMENT_SCHEMA,
            transcript_read,
        ),
        (
            "core.runtime.transcript.message.read",
            "Read an explicit character window from one authorized transcript message.",
            TRANSCRIPT_MESSAGE_READ_ARGUMENT_SCHEMA,
            message_read,
        ),
    ]
    return [
        (
            core_mcp_tool(
                tool_name=tool_name,
                description=description,
                owner_id="runtime",
                invocation_policy=WORKSPACE_SAFE,
                input_schema=schema,
            ),
            handler,
        )
        for tool_name, description, schema, handler in definitions
    ]


def _read_context(context: McpInvocationContext) -> RuntimeTranscriptReadContext:
    return RuntimeTranscriptReadContext(
        workspace_id=str(context.workspace_id or ""),
        user_id=context.user_id,
        platform_role=context.platform_role,
        workspace_role=context.workspace_role,
        caller_runtime_session_id=context.runtime_session_id,
    )


def _required_store(store: RuntimeStore | None) -> RuntimeStore:
    if store is None:
        raise RuntimeTranscriptValidationError("runtime_store_unavailable")
    return store


def _run(operation: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return operation()
    except RuntimeTranscriptAccessError as error:
        return {"error": error.reason, "status_code": error.status_code}
    except RuntimeTranscriptValidationError as error:
        return {"error": str(error), "status_code": 400}
