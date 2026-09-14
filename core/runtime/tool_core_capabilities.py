"""Execution-policy-owned filesystem and shell runtime tool surfaces."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from core.runtime.attachment_projection import (
    RuntimeAttachmentReadFence,
    attachment_read_fence_for_path,
)
from core.runtime.confined_filesystem import (
    ConfinedWorkspaceFilesystem,
    FilesystemRaceHook,
    ResourceClassificationResolver,
)
from core.runtime.full_access_filesystem import FullAccessFilesystem
from core.runtime.hosted_full_access_shell import (
    full_access_process_environment,
    run_full_access_command,
)
from core.runtime.tool_catalog import (
    RuntimeCoreCapabilitySurface,
    RuntimeExternalToolSurface,
    RuntimeToolActorContext,
    RuntimeToolSurfaceResult,
)
from core.runtime.tool_errors import RuntimeToolError
from core.runtime.tool_filesystem_listing import (
    MAX_FILESYSTEM_LIST_DEPTH,
    MAX_FILESYSTEM_LIST_RESULTS,
    filesystem_list_schema,
)
from core.runtime.hosted_tool_process_registry import (
    HostedToolProcessRegistry,
    hosted_process_environment,
)
from core.runtime.hosted_workspace_shell import run_hosted_workspace_command
from core.runtime.hosted_workspace_effects import (
    parse_hosted_workspace_mutation_scopes,
)
from core.runtime.tool_discovery_capabilities import (
    build_discovery_first_capabilities,
)
from core.runtime.tool_full_workspace_capabilities import (
    build_full_workspace_capabilities,
)
from core.runtime.tool_full_workspace_support import (
    mutation_affected_instruction_prefixes,
    prepare_mutation_instruction_guard,
)
from core.runtime.tool_full_workspace_schemas import (
    extended_filesystem_write_schema,
    workspace_mutation_scopes_schema,
)
from core.runtime.tool_result_artifacts import (
    build_tool_result_artifact_capabilities,
)
from core.runtime.tool_result_classification import (
    filesystem_listing_classification_projection,
    filesystem_mutation_classification_projection,
    filesystem_read_classification_projection,
)
from core.runtime.runtime_paths import RuntimePathResolver


MAX_FILESYSTEM_READ_BYTES = 262_144
MAX_FILESYSTEM_WRITE_BYTES = 1_048_576
MAX_SHELL_OUTPUT_BYTES = 131_072
MAX_SHELL_TIMEOUT_SECONDS = 30
REVIEWED_TOOL_SCHEMA_COMPONENT = "tool-schema-catalog"


def build_core_runtime_tool_capabilities(
    *,
    workspace_id: str,
    workspace_root: Path,
    resource_classification_resolver: ResourceClassificationResolver | None = None,
    filesystem_race_hook: FilesystemRaceHook | None = None,
    runtime_root: Path | None = None,
    process_registry: HostedToolProcessRegistry | None = None,
    cli_registry=None,
    mcp_registry=None,
    tool_ledger=None,
    result_classification_resolver=None,
    workspace_spawn_observer: Callable[[str], None] | None = None,
    attachment_read_fences: tuple[RuntimeAttachmentReadFence, ...] = (),
    execution_mode: str = "sandbox",
) -> tuple[RuntimeCoreCapabilitySurface, ...]:
    """Build sandboxed or direct full-access Core capabilities."""
    full_access = execution_mode == "full-access"
    if execution_mode not in {"sandbox", "full-access"}:
        raise RuntimeToolError("tool_execution_mode_mismatch")
    filesystem = (
        FullAccessFilesystem(
            workspace_id=workspace_id,
            workspace_root=workspace_root,
            classification_resolver=resource_classification_resolver,
        )
        if full_access
        else ConfinedWorkspaceFilesystem(
            workspace_id=workspace_id,
            workspace_root=workspace_root,
            classification_resolver=resource_classification_resolver,
            race_hook=filesystem_race_hook,
        )
    )
    path_resolver = RuntimePathResolver(
        workspace_id=workspace_id,
        workspace_root=workspace_root,
        execution_mode=execution_mode,
    )
    resolved_runtime_root = runtime_root or (workspace_root / "runtime")

    def tool_path(value: object, *, allow_root: bool) -> str:
        resolved = path_resolver.resolve(value, allow_root=allow_root)
        return (
            str(resolved.absolute)
            if full_access
            else resolved.for_confined_filesystem()
        )

    def filesystem_list(
        arguments: dict[str, object],
        context: RuntimeToolActorContext,
        _idempotency_key: str | None,
    ) -> RuntimeToolSurfaceResult:
        _require_context(context, workspace_id)
        max_depth = arguments.get("max_depth", 1)
        page_size = arguments.get("max_results", 200)
        if (
            not isinstance(max_depth, int)
            or isinstance(max_depth, bool)
            or not 1 <= max_depth <= MAX_FILESYSTEM_LIST_DEPTH
            or not isinstance(page_size, int)
            or isinstance(page_size, bool)
            or not 1 <= page_size <= MAX_FILESYSTEM_LIST_RESULTS
        ):
            raise RuntimeToolError("tool_arguments_invalid")
        result = filesystem.list_entries(
            tool_path(str(arguments.get("path") or "."), allow_root=True),
            max_depth=max_depth,
            page_size=page_size,
            cursor=(
                str(arguments["cursor"])
                if isinstance(arguments.get("cursor"), str)
                else None
            ),
        )
        return RuntimeToolSurfaceResult(
            result.payload,
            result.classification,
            (
                None
                if full_access
                else filesystem_listing_classification_projection(result.payload)
            ),
        )

    def filesystem_read(
        arguments: dict[str, object],
        context: RuntimeToolActorContext,
        _idempotency_key: str | None,
    ) -> RuntimeToolSurfaceResult:
        _require_context(context, workspace_id)
        requested = arguments.get("max_bytes", MAX_FILESYSTEM_READ_BYTES)
        offset = arguments.get("offset", 0)
        if (
            not isinstance(requested, int)
            or isinstance(requested, bool)
            or requested < 1
            or not isinstance(offset, int)
            or isinstance(offset, bool)
            or offset < 0
        ):
            raise RuntimeToolError("tool_arguments_invalid")
        encoding = str(arguments.get("encoding") or "utf-8")
        if encoding not in {"utf-8", "base64"}:
            raise RuntimeToolError("tool_arguments_invalid")
        path = tool_path(arguments.get("path"), allow_root=False)
        expected_identity = _optional_string(
            arguments.get("expected_resource_identity")
        )
        expected_revision = _optional_string(
            arguments.get("expected_resource_revision")
        )
        expected_digest = _optional_string(
            arguments.get("expected_resource_digest")
        )
        attachment_fence = attachment_read_fence_for_path(
            attachment_read_fences,
            path,
        )
        if attachment_fence is not None:
            if encoding != attachment_fence.read_encoding:
                raise RuntimeToolError("attachment_read_encoding_mismatch")
            expected_identity = _attachment_fence_value(
                expected_identity,
                attachment_fence.resource_identity,
            )
            expected_revision = _attachment_fence_value(
                expected_revision,
                attachment_fence.resource_revision,
            )
            expected_digest = _attachment_fence_value(
                expected_digest,
                attachment_fence.resource_digest,
            )
        reader = filesystem.read_text if encoding == "utf-8" else filesystem.read_bytes
        result = reader(
            path,
            offset=offset,
            max_bytes=min(requested, MAX_FILESYSTEM_READ_BYTES),
            expected_resource_identity=expected_identity,
            expected_resource_revision=expected_revision,
            expected_resource_digest=expected_digest,
        )
        return RuntimeToolSurfaceResult(
            result.payload,
            result.classification,
            (
                None
                if full_access
                else filesystem_read_classification_projection(result.payload)
            ),
        )

    def filesystem_write(
        arguments: dict[str, object],
        context: RuntimeToolActorContext,
        _idempotency_key: str | None,
    ) -> RuntimeToolSurfaceResult:
        _require_context(context, workspace_id)
        content = arguments.get("content")
        if not isinstance(content, str):
            raise RuntimeToolError("tool_arguments_invalid")
        if len(content.encode("utf-8")) > MAX_FILESYSTEM_WRITE_BYTES:
            raise RuntimeToolError("filesystem_write_too_large")
        path = tool_path(arguments.get("path"), allow_root=False)
        guard = None
        if not full_access:
            guard = prepare_mutation_instruction_guard(
                filesystem,
                workspace_root=workspace_root,
                path=path,
                expected_digest=_required_string(
                    arguments.get("instruction_scope_digest")
                ),
                affected_instruction_prefixes=mutation_affected_instruction_prefixes(
                    path,
                    target_is_directory=False,
                ),
            )
        result = filesystem.write_text(
            path,
            content=content,
            create_only=arguments.get("create_only") is True,
            create_parents=arguments.get("create_parents") is not False,
            replace_only=arguments.get("replace_only") is True,
            expected_resource_identity=_optional_string(
                arguments.get("expected_resource_identity")
            ),
            expected_resource_revision=_optional_string(
                arguments.get("expected_resource_revision")
            ),
            mutation_guard=guard,
        )
        payload = {
            **result.payload,
            **({} if guard is None else guard.evidence),
        }
        return RuntimeToolSurfaceResult(
            payload,
            result.classification,
            (
                None
                if full_access
                else filesystem_mutation_classification_projection(payload)
            ),
        )

    def shell_run(
        arguments: dict[str, object],
        context: RuntimeToolActorContext,
        _idempotency_key: str | None,
    ) -> dict[str, object]:
        _require_context(context, workspace_id)
        if context.execution_mode != "full-access":
            raise RuntimeToolError("shell_requires_full_access")
        argv = arguments.get("argv")
        if (
            not isinstance(argv, list)
            or not argv
            or len(argv) > 64
            or any(
                not isinstance(item, str) or not item or len(item) > 4096
                for item in argv
            )
        ):
            raise RuntimeToolError("tool_arguments_invalid")
        timeout = arguments.get("timeout_seconds", MAX_SHELL_TIMEOUT_SECONDS)
        if (
            not isinstance(timeout, int)
            or isinstance(timeout, bool)
            or not 1 <= timeout <= MAX_SHELL_TIMEOUT_SECONDS
        ):
            raise RuntimeToolError("tool_arguments_invalid")
        cwd = tool_path(str(arguments.get("cwd") or "."), allow_root=True)
        if full_access:
            return run_full_access_command(
                workspace_id=workspace_id,
                workspace_root=workspace_root,
                argv=argv,
                cwd=cwd,
                environment=full_access_process_environment(
                    workspace_id=workspace_id,
                    session_id=context.session_id,
                    workspace_root=workspace_root,
                ),
                timeout_seconds=timeout,
                max_output_bytes=MAX_SHELL_OUTPUT_BYTES,
                execution_control=context.execution_control,
                spawn_observer=workspace_spawn_observer,
            )
        return run_hosted_workspace_command(
            filesystem,
            workspace_root=workspace_root,
            runtime_root=resolved_runtime_root,
            argv=argv,
            cwd=cwd,
            environment=hosted_process_environment(
                session_id=context.session_id
            ),
            timeout_seconds=timeout,
            max_output_bytes=MAX_SHELL_OUTPUT_BYTES,
            mutation_scopes=parse_hosted_workspace_mutation_scopes(
                arguments.get("mutation_scopes")
            ),
            execution_control=context.execution_control,
            result_classification_resolver=result_classification_resolver,
            result_context=context,
            result_arguments=arguments,
            spawn_observer=workspace_spawn_observer,
        )

    base = (
        RuntimeCoreCapabilitySurface(
            definition=_core_surface(
                handle="core-capability:filesystem.list",
                description=(
                    "List a paginated host directory without reading file content."
                    if full_access
                    else "List a stable, paginated workspace snapshot without reading file content."
                ),
                input_schema=filesystem_list_schema(),
                effect_class="read",
                safe_to_retry=True,
            ),
            handler=filesystem_list,
            allowed_execution_modes=("sandbox", "full-access"),
        ),
        RuntimeCoreCapabilitySurface(
            definition=_core_surface(
                handle="core-capability:filesystem.read",
                description=(
                    "Read one UTF-8 or base64 byte chunk from a host path."
                    if full_access
                    else "Read one mutation-detecting UTF-8 or base64 byte chunk through a workspace descriptor."
                ),
                input_schema=_filesystem_read_schema(),
                effect_class="read",
                safe_to_retry=True,
            ),
            handler=filesystem_read,
            allowed_execution_modes=("sandbox", "full-access"),
        ),
        RuntimeCoreCapabilitySurface(
            definition=_core_surface(
                handle="core-capability:filesystem.write",
                description=(
                    "Atomically write a UTF-8 host file."
                    if full_access
                    else "Atomically write through a verified workspace parent descriptor."
                ),
                input_schema=extended_filesystem_write_schema(
                    MAX_FILESYSTEM_WRITE_BYTES,
                    full_access=full_access,
                ),
                effect_class="mutating",
            ),
            handler=filesystem_write,
            allowed_execution_modes=("sandbox", "full-access"),
        ),
        RuntimeCoreCapabilitySurface(
            definition=_core_surface(
                handle="core-capability:shell.run",
                description="Run one argv command in the authorized host environment.",
                input_schema=_shell_schema(full_access=full_access),
                effect_class="destructive",
            ),
            handler=shell_run,
            allowed_execution_modes=("full-access",),
        ),
    )
    full_workspace = build_full_workspace_capabilities(
        filesystem=filesystem,
        workspace_root=workspace_root,
        runtime_root=resolved_runtime_root,
        process_registry=process_registry,
        result_classification_resolver=result_classification_resolver,
        full_access=full_access,
    )
    discovery = (
        build_discovery_first_capabilities(
            cli_registry=cli_registry,
            mcp_registry=mcp_registry,
            result_classification_resolver=result_classification_resolver,
        )
        if cli_registry is not None and mcp_registry is not None
        else ()
    )
    artifacts = (
        build_tool_result_artifact_capabilities(
            ledger=tool_ledger,
            workspace_id=workspace_id,
        )
        if tool_ledger is not None
        else ()
    )
    return (*base, *full_workspace, *discovery, *artifacts)


def _core_surface(
    *,
    handle: str,
    description: str,
    input_schema: dict[str, object],
    effect_class: str,
    safe_to_retry: bool = False,
) -> RuntimeExternalToolSurface:
    return RuntimeExternalToolSurface(
        handle=handle,
        description=description,
        input_schema=input_schema,
        output_schema=None,
        effect_class=effect_class,  # type: ignore[arg-type]
        safe_to_retry=safe_to_retry,
        owner_kind="core",
        schema_public=True,
        reviewed_schema_component=REVIEWED_TOOL_SCHEMA_COMPONENT,
    )


def _require_context(context: RuntimeToolActorContext, workspace_id: str) -> None:
    if context.workspace_id != workspace_id:
        raise RuntimeToolError("tool_workspace_mismatch")


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise RuntimeToolError("tool_arguments_invalid")
    return value


def _required_string(value: object) -> str:
    resolved = _optional_string(value)
    if resolved is None:
        raise RuntimeToolError("tool_arguments_invalid")
    return resolved


def _attachment_fence_value(
    requested: str | None,
    observed: str,
) -> str:
    if requested is not None and requested != observed:
        raise RuntimeToolError("filesystem_resource_changed")
    return observed


def _filesystem_read_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "path": {"type": "string", "minLength": 1, "maxLength": 4096},
            "offset": {"type": "integer", "minimum": 0},
            "max_bytes": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_FILESYSTEM_READ_BYTES,
            },
            "encoding": {
                "type": "string",
                "enum": ["utf-8", "base64"],
            },
            "expected_resource_identity": {
                "type": "string",
                "minLength": 1,
                "maxLength": 256,
            },
            "expected_resource_revision": {
                "type": "string",
                "minLength": 64,
                "maxLength": 64,
            },
            "expected_resource_digest": {
                "type": "string",
                "minLength": 64,
                "maxLength": 64,
            },
        },
        "required": ["path"],
        "additionalProperties": False,
    }


def _shell_schema(*, full_access: bool) -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "argv": {
                "type": "array",
                "items": {"type": "string", "minLength": 1, "maxLength": 4096},
                "minItems": 1,
                "maxItems": 64,
            },
            "cwd": {"type": "string", "minLength": 1, "maxLength": 4096},
            "timeout_seconds": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_SHELL_TIMEOUT_SECONDS,
            },
            **(
                {}
                if full_access
                else {"mutation_scopes": workspace_mutation_scopes_schema()}
            ),
        },
        "required": ["argv"] if full_access else ["argv", "mutation_scopes"],
        "additionalProperties": False,
    }
