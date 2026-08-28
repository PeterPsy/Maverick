"""Session-owned process capability surfaces for Full Workspace profiles."""

from __future__ import annotations

from core.runtime.hosted_tool_process_registry import hosted_process_environment
from core.runtime.tool_errors import RuntimeToolError
from core.runtime.tool_full_workspace_schemas import (
    process_input_schema,
    process_interrupt_schema,
    process_start_schema,
    process_status_schema,
)
from core.runtime.tool_full_workspace_support import (
    argv_argument,
    full_workspace_surface,
    integer_argument,
    mutation_instruction_evidence,
    optional_string,
    require_workspace_context,
    required_string,
    unclassified_process_result,
)


def build_process_capabilities(
    registry,
    *,
    filesystem,
    workspace_root,
    runtime_root,
):
    """Build process start/status/input/interrupt surfaces for one workspace."""

    def start(arguments, context, _idempotency_key):
        require_workspace_context(context, filesystem.workspace_id)
        if context.execution_mode != "full-access":
            raise RuntimeToolError("shell_requires_full_access")
        argv = argv_argument(arguments.get("argv"))
        cwd = str(arguments.get("cwd") or ".")
        mutation_instruction_evidence(
            filesystem,
            workspace_root=workspace_root,
            path=cwd,
            expected_digest=optional_string(
                arguments.get("instruction_scope_digest")
            ),
            target_is_directory=True,
        )
        result = registry.start(
            filesystem=filesystem,
            workspace_id=context.workspace_id,
            session_id=context.session_id,
            workspace_root=workspace_root,
            runtime_root=runtime_root,
            argv=argv,
            cwd=cwd,
            environment=hosted_process_environment(session_id=context.session_id),
            timeout_seconds=integer_argument(
                arguments.get("timeout_seconds", 300),
                minimum=1,
                maximum=3_600,
            ),
        )
        return unclassified_process_result(result, context.session_id)

    def status(arguments, context, _idempotency_key):
        result = registry.status(
            process_id=required_string(arguments.get("process_id")),
            session_id=context.session_id,
            workspace_id=context.workspace_id,
            output_offset=integer_argument(
                arguments.get("output_offset", 0),
                minimum=0,
            ),
            max_bytes=integer_argument(
                arguments.get("max_bytes", 65_536),
                minimum=1,
                maximum=131_072,
            ),
        )
        return unclassified_process_result(result, context.session_id)

    def write_input(arguments, context, _idempotency_key):
        result = registry.write_input(
            process_id=required_string(arguments.get("process_id")),
            session_id=context.session_id,
            workspace_id=context.workspace_id,
            content=required_string(arguments.get("content"), allow_empty=True),
            close=arguments.get("close") is True,
        )
        return unclassified_process_result(result, context.session_id)

    def interrupt(arguments, context, _idempotency_key):
        result = registry.interrupt(
            process_id=required_string(arguments.get("process_id")),
            session_id=context.session_id,
            workspace_id=context.workspace_id,
        )
        return unclassified_process_result(result, context.session_id)

    return (
        full_workspace_surface(
            "process.start",
            "Start a long-running confined workspace process.",
            process_start_schema(),
            "destructive",
            start,
            modes=("full-access",),
        ),
        full_workspace_surface(
            "process.status",
            "Read a bounded output chunk and current process status.",
            process_status_schema(),
            "read",
            status,
            modes=("full-access",),
        ),
        full_workspace_surface(
            "process.input",
            "Write bounded UTF-8 input to a live process.",
            process_input_schema(),
            "mutating",
            write_input,
            modes=("full-access",),
        ),
        full_workspace_surface(
            "process.interrupt",
            "Terminate a live process and its descendants.",
            process_interrupt_schema(),
            "destructive",
            interrupt,
            modes=("full-access",),
        ),
    )
