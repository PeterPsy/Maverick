"""Read-only core CLI commands for authorized runtime transcripts."""

from __future__ import annotations

from typing import Any, Callable

from core.cli.core_command_helpers import WORKSPACE_SAFE, core_cli_command
from core.cli.models import CliCommandDefinition, CliInvocationContext
from core.device_use.audit import read_device_use_audit, read_device_use_call
from core.device_use.evidence import DeviceUseEvidenceArchive
from core.runtime.errors import RuntimeTranscriptAccessError, RuntimeTranscriptValidationError
from core.runtime.store import RuntimeStore
from core.runtime.usage_read import read_runtime_usage
from core.runtime.transcript_models import RuntimeTranscriptReadContext
from core.runtime.transcript_schemas import (
    THREAD_LIST_ARGUMENT_SCHEMA,
    TRANSCRIPT_MESSAGE_READ_ARGUMENT_SCHEMA,
    TRANSCRIPT_READ_ARGUMENT_SCHEMA,
    DEVICE_USE_AUDIT_ARGUMENT_SCHEMA,
    DEVICE_USE_CALL_ARGUMENT_SCHEMA,
)
from core.runtime.transcript_service import (
    list_runtime_transcript_threads,
    read_runtime_transcript,
    read_runtime_transcript_message,
)


def runtime_transcript_command_specs(
    *,
    runtime_store: RuntimeStore | None = None,
    usage_store=None,
    observability_store=None,
    start_path=None,
) -> list[tuple[CliCommandDefinition, Any]]:
    """Build transcript CLI commands over the core runtime store."""

    def threads_list(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        return _run(
            "core.runtime.threads.list",
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
                surface="cli",
            ),
        )

    def transcript_read(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        return _run(
            "core.runtime.transcript.read",
            lambda: read_runtime_transcript(
                _required_store(runtime_store),
                context=_read_context(context),
                thread_id=str(arguments.get("thread_id") or ""),
                limit=arguments.get("limit", 30),
                before_cursor=arguments.get("before_cursor"),
                snapshot_cursor=arguments.get("snapshot_cursor"),
                profile=str(arguments.get("profile") or "messages"),
                observability_store=observability_store,
                surface="cli",
            ),
        )

    def message_read(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        return _run(
            "core.runtime.transcript.message.read",
            lambda: read_runtime_transcript_message(
                _required_store(runtime_store),
                context=_read_context(context),
                thread_id=str(arguments.get("thread_id") or ""),
                message_id=str(arguments.get("message_id") or ""),
                offset=arguments.get("offset", 0),
                max_chars=arguments.get("max_chars", 12000),
                snapshot_cursor=arguments.get("snapshot_cursor"),
                observability_store=observability_store,
                surface="cli",
            ),
        )

    def usage_read(arguments, context):
        return _run("core.runtime.usage.read", lambda: read_runtime_usage(
            _required_store(runtime_store), usage_store=usage_store, context=_read_context(context),
            thread_id=str(arguments.get("thread_id") or ""), turn_id=arguments.get("turn_id"),
        ))

    def audit_read(arguments, context):
        return _run("core.runtime.device-use.audit.read", lambda: read_device_use_audit(
            _required_store(runtime_store), context=_read_context(context),
            thread_id=str(arguments.get("thread_id") or ""), limit=arguments.get("limit", 30),
            before_cursor=arguments.get("before_cursor"), usage_store=usage_store,
        ))

    def call_read(arguments, context):
        return _run("core.runtime.device-use.call.read", lambda: read_device_use_call(
            _required_store(runtime_store),
            archive=DeviceUseEvidenceArchive.for_repository(_required_store(runtime_store), start_path),
            context=_read_context(context), thread_id=str(arguments.get("thread_id") or ""),
            turn_id=str(arguments.get("turn_id") or ""), call_id=str(arguments.get("call_id") or ""),
            offset=arguments.get("offset", 0), max_chars=arguments.get("max_chars", 12000),
        ))

    definitions = [
        ("core.runtime.usage.read", ["core", "runtime", "usage", "read"],
         "Read authorized chat consumption, cached input, active context and estimated cost from Core Usage.",
         {"type": "object", "properties": {"thread_id": {"type": "string", "minLength": 1, "maxLength": 240},
          "turn_id": {"type": "string", "minLength": 1, "maxLength": 240, "description": "Optional direct-turn usage; excludes delegated children."}},
          "required": ["thread_id"], "additionalProperties": False}, usage_read),

        (
            "core.runtime.device-use.audit.read", ["core", "runtime", "device-use", "audit", "read"],
            "Read authorized native call lifecycle, evidence availability and measured turn timings.",
            DEVICE_USE_AUDIT_ARGUMENT_SCHEMA, audit_read,
        ),
        (
            "core.runtime.device-use.call.read", ["core", "runtime", "device-use", "call", "read"],
            "Read a bounded encrypted native evidence window as the thread owner or admin; typed text is withheld.",
            DEVICE_USE_CALL_ARGUMENT_SCHEMA, call_read,
        ),

        (
            "core.runtime.threads.list",
            ["core", "runtime", "threads", "list"],
            "List only runtime threads whose transcripts the caller may read.",
            THREAD_LIST_ARGUMENT_SCHEMA,
            threads_list,
        ),
        (
            "core.runtime.transcript.read",
            ["core", "runtime", "transcript", "read"],
            "Read a bounded page of untrusted conversation messages from complete runtime history.",
            TRANSCRIPT_READ_ARGUMENT_SCHEMA,
            transcript_read,
        ),
        (
            "core.runtime.transcript.message.read",
            ["core", "runtime", "transcript", "message", "read"],
            "Read an explicit character window from one authorized transcript message.",
            TRANSCRIPT_MESSAGE_READ_ARGUMENT_SCHEMA,
            message_read,
        ),
    ]
    return [
        (
            core_cli_command(
                command_id=command_id,
                path_segments=path,
                description=description,
                owner_id="runtime",
                invocation_policy=WORKSPACE_SAFE,
                argument_schema=schema,
            ),
            handler,
        )
        for command_id, path, description, schema, handler in definitions
    ]


def _read_context(context: CliInvocationContext) -> RuntimeTranscriptReadContext:
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


def _run(command_id: str, operation: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return {"command_id": command_id, **operation()}
    except RuntimeTranscriptAccessError as error:
        return {"command_id": command_id, "error": error.reason, "status_code": error.status_code}
    except RuntimeTranscriptValidationError as error:
        return {"command_id": command_id, "error": str(error), "status_code": 400}
