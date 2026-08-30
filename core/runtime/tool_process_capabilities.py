"""Session-owned process capability surfaces for Full Workspace profiles."""

from __future__ import annotations

import hashlib
import json

from core.egress.classification import fail_closed_classification
from core.runtime.tool_catalog import RuntimeToolSurfaceResult
from core.runtime.hosted_tool_process_registry import hosted_process_environment
from core.runtime.hosted_workspace_effects import (
    parse_hosted_workspace_mutation_scopes,
)
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
    require_workspace_context,
    required_string,
)


def build_process_capabilities(
    registry,
    *,
    filesystem,
    workspace_root,
    runtime_root,
    result_classification_resolver=None,
):
    """Build process start/status/input/interrupt surfaces for one workspace."""

    def start(arguments, context, _idempotency_key):
        require_workspace_context(context, filesystem.workspace_id)
        if context.execution_mode != "full-access":
            raise RuntimeToolError("shell_requires_full_access")
        if context.execution_control is not None:
            context.execution_control.check()
        argv = argv_argument(arguments.get("argv"))
        cwd = str(arguments.get("cwd") or ".")
        mutation_scopes = parse_hosted_workspace_mutation_scopes(
            arguments.get("mutation_scopes")
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
            mutation_scopes=mutation_scopes,
        )
        _register_process_cancellation(
            registry,
            process_id=str(result.get("process_id") or ""),
            context=context,
        )
        return _classified_result(
            result,
            handle="core-capability:process.start",
            arguments=arguments,
            context=context,
            resolver=result_classification_resolver,
        )

    def status(arguments, context, _idempotency_key):
        process_id = required_string(arguments.get("process_id"))
        _register_process_cancellation(
            registry,
            process_id=process_id,
            context=context,
        )
        result = registry.status(
            process_id=process_id,
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
            execution_control=context.execution_control,
        )
        return _classified_result(
            result,
            handle="core-capability:process.status",
            arguments=arguments,
            context=context,
            resolver=result_classification_resolver,
        )

    def write_input(arguments, context, _idempotency_key):
        process_id = required_string(arguments.get("process_id"))
        _register_process_cancellation(
            registry,
            process_id=process_id,
            context=context,
        )
        result = registry.write_input(
            process_id=process_id,
            session_id=context.session_id,
            workspace_id=context.workspace_id,
            content=required_string(arguments.get("content"), allow_empty=True),
            close=arguments.get("close") is True,
        )
        return _classified_result(
            result,
            handle="core-capability:process.input",
            arguments=arguments,
            context=context,
            resolver=result_classification_resolver,
        )

    def interrupt(arguments, context, _idempotency_key):
        result = registry.interrupt(
            process_id=required_string(arguments.get("process_id")),
            session_id=context.session_id,
            workspace_id=context.workspace_id,
        )
        return _classified_result(
            result,
            handle="core-capability:process.interrupt",
            arguments=arguments,
            context=context,
            resolver=result_classification_resolver,
        )

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
            "Poll bounded output and commit governed effects on terminal success.",
            process_status_schema(),
            "mutating",
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


def _classified_result(result, *, handle, arguments, context, resolver):
    if resolver is not None:
        classification = resolver(handle, arguments, result, context)
        if isinstance(classification, RuntimeToolSurfaceResult):
            return classification
        if classification is None:
            classification = _fallback_classification(
                result,
                handle=handle,
                context=context,
            )
    else:
        classification = _fallback_classification(
            result,
            handle=handle,
            context=context,
        )
    return RuntimeToolSurfaceResult(result, classification)


def _register_process_cancellation(registry, *, process_id, context) -> None:
    control = context.execution_control
    if control is None:
        return
    control.add_cancellation_callback(
        lambda: _cancel_managed_process(
            registry,
            process_id=process_id,
            session_id=context.session_id,
            workspace_id=context.workspace_id,
        )
    )
    control.check()


def _cancel_managed_process(
    registry,
    *,
    process_id: str,
    session_id: str,
    workspace_id: str,
) -> None:
    try:
        registry.interrupt(
            process_id=process_id,
            session_id=session_id,
            workspace_id=workspace_id,
        )
    except Exception:
        # Session close/orphan cleanup remains the final fallback. Cancellation
        # must still release the control lock and let the worker observe its fence.
        pass


def _fallback_classification(result, *, handle, context):
    result_digest = hashlib.sha256(
        json.dumps(
            result,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return fail_closed_classification(
        provenance="tool_result",
        source_ref=handle,
        source_revision=result_digest,
        source_digest=result_digest,
        resource_identity=f"hosted-process:{context.session_id}:{handle}",
    )
