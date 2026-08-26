"""Execution-policy-owned filesystem and shell runtime tool surfaces."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

from core.runtime.confined_filesystem import (
    ConfinedWorkspaceFilesystem,
    FilesystemRaceHook,
    ResourceClassificationResolver,
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


MAX_FILESYSTEM_READ_BYTES = 262_144
MAX_FILESYSTEM_WRITE_BYTES = 1_048_576
MAX_SHELL_OUTPUT_BYTES = 131_072
MAX_SHELL_TIMEOUT_SECONDS = 30
CERTIFIED_TOOL_SCHEMA_TCB_COMPONENT = "tool-schema-catalog"


def build_core_runtime_tool_capabilities(
    *,
    workspace_id: str,
    workspace_root: Path,
    resource_classification_resolver: ResourceClassificationResolver | None = None,
    filesystem_race_hook: FilesystemRaceHook | None = None,
) -> tuple[RuntimeCoreCapabilitySurface, ...]:
    """Build workspace-bound Core capabilities over one fd-relative boundary."""
    filesystem = ConfinedWorkspaceFilesystem(
        workspace_id=workspace_id,
        workspace_root=workspace_root,
        classification_resolver=resource_classification_resolver,
        race_hook=filesystem_race_hook,
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
            str(arguments.get("path") or "."),
            max_depth=max_depth,
            page_size=page_size,
            cursor=(
                str(arguments["cursor"])
                if isinstance(arguments.get("cursor"), str)
                else None
            ),
        )
        return RuntimeToolSurfaceResult(result.payload, result.classification)

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
        result = filesystem.read_text(
            str(arguments.get("path") or ""),
            offset=offset,
            max_bytes=min(requested, MAX_FILESYSTEM_READ_BYTES),
            expected_resource_identity=_optional_string(
                arguments.get("expected_resource_identity")
            ),
            expected_resource_revision=_optional_string(
                arguments.get("expected_resource_revision")
            ),
        )
        return RuntimeToolSurfaceResult(result.payload, result.classification)

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
        result = filesystem.write_text(
            str(arguments.get("path") or ""),
            content=content,
            create_only=arguments.get("create_only") is True,
            create_parents=arguments.get("create_parents") is not False,
        )
        return RuntimeToolSurfaceResult(result.payload, result.classification)

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
        chain = filesystem.open_shell_cwd(str(arguments.get("cwd") or "."))
        environment = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        }
        cwd_fd = chain.leaf_fd
        try:
            completed = subprocess.run(
                argv,
                cwd=None,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
                pass_fds=(cwd_fd,),
                preexec_fn=lambda: os.fchdir(cwd_fd),
            )
            filesystem.assert_shell_cwd(chain)
        except RuntimeToolError:
            raise
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RuntimeToolError("shell_execution_failed") from error
        finally:
            chain.close()
        output = completed.stdout[: MAX_SHELL_OUTPUT_BYTES + 1]
        if len(output) > MAX_SHELL_OUTPUT_BYTES:
            raise RuntimeToolError("shell_output_too_large")
        return {
            "exit_code": completed.returncode,
            "output": output.decode("utf-8", errors="replace"),
            "output_bytes": len(output),
        }

    return (
        RuntimeCoreCapabilitySurface(
            definition=_core_surface(
                handle="core-capability:filesystem.list",
                description=(
                    "List a stable, paginated workspace snapshot without reading file content."
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
                    "Read one mutation-detecting UTF-8 chunk through a workspace descriptor."
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
                description="Atomically write through a verified workspace parent descriptor.",
                input_schema=_filesystem_write_schema(),
                effect_class="mutating",
            ),
            handler=filesystem_write,
            allowed_execution_modes=("sandbox", "full-access"),
        ),
        RuntimeCoreCapabilitySurface(
            definition=_core_surface(
                handle="core-capability:shell.run",
                description="Run one argv command from a retained workspace directory descriptor.",
                input_schema=_shell_schema(),
                effect_class="destructive",
            ),
            handler=shell_run,
            allowed_execution_modes=("full-access",),
        ),
    )


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
        certified_tcb_component=CERTIFIED_TOOL_SCHEMA_TCB_COMPONENT,
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
        },
        "required": ["path"],
        "additionalProperties": False,
    }


def _filesystem_write_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "path": {"type": "string", "minLength": 1, "maxLength": 4096},
            "content": {"type": "string", "maxLength": MAX_FILESYSTEM_WRITE_BYTES},
            "create_only": {"type": "boolean"},
            "create_parents": {"type": "boolean"},
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    }


def _shell_schema() -> dict[str, object]:
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
        },
        "required": ["argv"],
        "additionalProperties": False,
    }
